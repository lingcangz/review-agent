import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from review_agent_api.db_models import ReviewContext, ReviewRule
from review_agent_api.models import Finding
from review_agent_api.worker import (
    ContextLimitExceededError,
    InvalidModelOutputError,
    ModelTimeoutError,
    run_model,
    verified_findings,
)


def _completed_response() -> str:
    return json.dumps(
        {
            "status": "completed",
            "report": "未发现可确认问题。",
            "findings": [],
            "requested_context": [],
        }
    )


def _context(content: str = "secret_context()\n") -> ReviewContext:
    return ReviewContext(
        organization_id="org",
        review_id="review",
        path="src/a.py",
        start_line=10,
        end_line=10,
        content=content,
        raw_content_expires_at=None,
    )


def _rule() -> ReviewRule:
    return ReviewRule(
        organization_id="org", name="团队规则", instruction="只报告直接证据", enabled=True
    )


def test_model_input_has_rules_static_results_strict_schema_and_tool_only_context(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResponses:
        async def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            if len(calls) == 1:
                return type(
                    "Response",
                    (),
                    {
                        "id": "first",
                        "output": [
                            {
                                "type": "function_call",
                                "name": "request_context",
                                "call_id": "call-1",
                                "arguments": '{"path":"src/a.py","start_line":10,"end_line":10}',
                            }
                        ],
                        "output_text": "",
                    },
                )()
            return type(
                "Response", (), {"id": "second", "output": [], "output_text": _completed_response()}
            )()

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            self.responses = FakeResponses()

        async def close(self) -> None:
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("review_agent_api.worker.AsyncOpenAI", FakeClient)
    result = asyncio.run(
        run_model(
            "+++ b/src/a.py\n@@ -1 +10 @@\n-old\n+new_value()",
            [_context()],
            [_rule()],
            [{"tool": "Ruff", "path": "src/a.py", "line": 10, "message": "undefined name"}],
        )
    )

    assert result.status == "completed"
    initial = calls[0]
    assert "团队规则" in initial["input"]
    assert "undefined name" in initial["input"]
    assert "secret_context" not in initial["input"]
    assert initial["tools"][0]["name"] == "request_context"
    assert initial["tools"][0]["strict"] is True
    assert initial["text"]["format"]["strict"] is True
    tool_output = json.loads(calls[1]["input"][0]["output"])
    assert tool_output["content"] == "secret_context()\n"


@pytest.mark.parametrize(
    ("response_text", "error_type"),
    [
        ("not-json", InvalidModelOutputError),
        (
            json.dumps(
                {
                    "status": "needs_context",
                    "report": "需要更多代码。",
                    "findings": [],
                    "requested_context": [{"path": "src/a.py", "start_line": 1, "end_line": 2}],
                }
            ),
            InvalidModelOutputError,
        ),
    ],
)
def test_model_rejects_invalid_structured_output(
    monkeypatch, response_text: str, error_type: type[Exception]
) -> None:
    class FakeResponses:
        async def create(self, **_kwargs: Any) -> Any:
            return type("Response", (), {"output": [], "output_text": response_text})()

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            self.responses = FakeResponses()

        async def close(self) -> None:
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("review_agent_api.worker.AsyncOpenAI", FakeClient)
    with pytest.raises(error_type):
        asyncio.run(run_model("diff", [], []))


def test_model_timeout_and_context_limit_are_bounded(monkeypatch) -> None:
    class SlowResponses:
        async def create(self, **_kwargs: Any) -> Any:
            await asyncio.sleep(0.01)
            return type("Response", (), {"output": [], "output_text": _completed_response()})()

    class CallContextResponses:
        async def create(self, **_kwargs: Any) -> Any:
            return type(
                "Response",
                (),
                {
                    "output": [
                        {
                            "type": "function_call",
                            "name": "request_context",
                            "call_id": "call-1",
                            "arguments": '{"path":"src/a.py","start_line":10,"end_line":10}',
                        }
                    ],
                    "output_text": "",
                },
            )()

    class FakeClient:
        def __init__(self, responses: Any) -> None:
            self.responses = responses

        async def close(self) -> None:
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("review_agent_api.worker.MODEL_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        "review_agent_api.worker.AsyncOpenAI", lambda **_kwargs: FakeClient(SlowResponses())
    )
    with pytest.raises(ModelTimeoutError):
        asyncio.run(run_model("diff", [], []))

    monkeypatch.setattr("review_agent_api.worker.MODEL_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(
        "review_agent_api.worker.AsyncOpenAI", lambda **_kwargs: FakeClient(CallContextResponses())
    )
    with pytest.raises(ContextLimitExceededError):
        asyncio.run(run_model("diff", [_context("x" * 100_001)], []))


def test_server_filters_unanchored_unsupported_and_duplicate_findings() -> None:
    base = {
        "confidence": "high",
        "category": "correctness",
        "path": "src/a.py",
        "start_line": 10,
        "end_line": 10,
        "title": "返回值错误",
        "evidence": "new_value() 被直接返回",
        "recommendation": "恢复原有返回值。",
    }
    first = Finding(severity="P1", **base)
    duplicate = Finding(severity="P2", **(base | {"recommendation": "补充回归测试。"}))
    unsupported = Finding(severity="P1", **(base | {"evidence": "没有输入中出现的证据"}))
    diff = "+++ b/src/a.py\n@@ -1 +10 @@\n-old\n+new_value()"

    verified = verified_findings([first, duplicate, unsupported], diff)

    assert len(verified) == 1
    assert verified[0].severity == "P1"
    assert "补充回归测试" in verified[0].recommendation
    with pytest.raises(ValidationError):
        Finding.model_validate(base | {"severity": "P9"})
    with pytest.raises(ValidationError):
        Finding.model_validate(base | {"confidence": "medium"})
