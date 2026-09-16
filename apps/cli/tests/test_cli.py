from pathlib import Path
from types import SimpleNamespace

import pytest

from review_agent_cli.config import CliConfig, save_config
from review_agent_cli.git import ChangedFile, ReviewInput
from review_agent_cli.main import (
    _confirm,
    _context_for_request,
    _initial_context,
    _poll_review,
    _read_context_range,
    _validate_input,
    run_history,
)
from review_agent_cli.safety import is_ignored, normalize_repository_path, redact_secrets


def test_windows_path_is_normalized_for_api() -> None:
    assert normalize_repository_path(r"src\service.py") == "src/service.py"
    with pytest.raises(ValueError):
        normalize_repository_path(r"..\secrets.env")


def test_empty_diff_is_rejected(tmp_path: Path) -> None:
    review_input = ReviewInput(tmp_path, "", ())

    with pytest.raises(ValueError, match="没有可审查"):
        _validate_input(review_input)


def test_review_confirmation_defaults_to_automatic_yes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    review_input = ReviewInput(tmp_path, "diff", (ChangedFile("a.py", "M", False),))

    _confirm(review_input, redacted_count=0, automatic=True)

    assert "已自动确认 y" in capsys.readouterr().out


def test_binary_and_ignored_changes_are_rejected(tmp_path: Path) -> None:
    (tmp_path / ".review-agentignore").write_text("secrets/**\n", encoding="utf-8")
    binary = ReviewInput(tmp_path, "diff", (ChangedFile("image.png", "M", True),))
    ignored = ReviewInput(tmp_path, "diff", (ChangedFile("secrets/app.py", "M", False),))

    with pytest.raises(ValueError, match="二进制"):
        _validate_input(binary)
    with pytest.raises(ValueError, match="保护"):
        _validate_input(ignored)


def test_secret_is_redacted_before_upload(tmp_path: Path) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    review_input = ReviewInput(
        tmp_path, f"+OPENAI_API_KEY={secret}\n", (ChangedFile("a.py", "M", False),)
    )

    diff, changed = _validate_input(review_input)

    assert secret not in diff
    assert "[已脱敏]" in diff
    assert changed == 1
    assert "private" not in redact_secrets("token=private")


def test_ignore_patterns_support_basename_and_negation() -> None:
    assert is_ignored("nested/deploy.key", ["*.key"])
    assert not is_ignored("secrets/example.env", ["secrets/**", "!secrets/example.env"])


def test_explicit_context_respects_line_range_and_redacts(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("one\nTOKEN=private\nthree\nfour\n", encoding="utf-8")

    context = _initial_context(tmp_path, ["service.py@2-3"])

    assert context == [
        {
            "path": "service.py",
            "start_line": 2,
            "end_line": 3,
            "content": "TOKEN=[已脱敏]\nthree\n",
        }
    ]
    with pytest.raises(ValueError, match="行范围"):
        _read_context_range(source, "service.py", 4, 2)


def test_context_callback_refuses_ignored_file_and_returns_only_requested_path(
    tmp_path: Path,
) -> None:
    (tmp_path / ".review-agentignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / "safe.py").write_text("print('safe')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=private\n", encoding="utf-8")

    assert _context_for_request(
        tmp_path, [{"path": "safe.py", "start_line": 1, "end_line": 1}]
    ) == [{"path": "safe.py", "start_line": 1, "end_line": 1, "content": "print('safe')\n"}]
    with pytest.raises(ValueError, match="保护"):
        _context_for_request(tmp_path, [{"path": ".env", "start_line": 1, "end_line": 1}])


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.responses = [
            {
                "status": "needs_context",
                "requested_context": [{"path": "safe.py", "start_line": 1, "end_line": 1}],
            },
            {"status": "completed", "report": "完成", "findings": []},
        ]

    def request(self, method: str, path: str, payload: object = None) -> dict[str, object]:
        self.calls.append((method, path, payload))
        if method == "POST":
            return {"status": "queued"}
        return self.responses.pop(0)


def test_poll_returns_requested_context_then_completed_result(tmp_path: Path) -> None:
    (tmp_path / "safe.py").write_text("print('safe')\n", encoding="utf-8")
    client = FakeClient()

    result = _poll_review(client, "review-1", tmp_path, interval=0.1, timeout=1)

    assert result["status"] == "completed"
    assert client.calls[1] == (
        "POST",
        "/v1/reviews/review-1/context",
        {
            "context": [
                {
                    "path": "safe.py",
                    "start_line": 1,
                    "end_line": 1,
                    "content": "print('safe')\n",
                }
            ]
        },
    )


def test_history_prefers_remote_api(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("REVIEW_AGENT_CONFIG", str(config_file))
    save_config(CliConfig(token="rap_test"))

    def fake_request(_self, method: str, path: str, payload: object = None) -> dict[str, object]:
        assert (method, path, payload) == ("GET", "/v1/reviews?limit=5", None)
        return {
            "items": [
                {
                    "review_id": "remote-1",
                    "status": "completed",
                    "created_at": "2026-09-16T00:00:00Z",
                }
            ]
        }

    monkeypatch.setattr("review_agent_cli.main.ApiClient.request", fake_request)

    run_history(SimpleNamespace(limit=5, api_url=None, token=None, local=False))

    assert "remote-1" in capsys.readouterr().out
