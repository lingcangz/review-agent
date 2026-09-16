"""arq orchestration for bounded, evidence-only OpenAI code reviews."""

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from os import getenv
from typing import Any, cast

from arq.connections import RedisSettings
from arq.typing import WorkerCoroutine, WorkerSettingsType
from arq.worker import func, run_worker
from openai import AsyncOpenAI
from pydantic import ValidationError
from sqlalchemy import delete, select

from review_agent_api.database import Database
from review_agent_api.db_models import Review, ReviewContext, ReviewFinding, ReviewRule
from review_agent_api.models import (
    ContextRequest,
    Finding,
    ReviewModelResult,
    StaticAnalysisFinding,
)
from review_agent_api.privacy import redact_secrets

MODEL_TIMEOUT_SECONDS = 90
MAX_CONTEXT_TOOL_CALLS = 20
MAX_CONTEXT_BYTES = 100_000

REVIEW_INSTRUCTIONS = """你是团队 Python Git 变更审阅器。仅报告可由提交 diff、静态分析结果，或
通过 request_context 工具取得的获准上下文直接证实的：1. 正确性缺陷；2. 安全漏洞；3. 此次变更
直接造成的回归。不要报告风格、重构建议、猜测或低置信度问题。只输出 confidence 为 high 的 finding。
每条 finding 必须定位到改动后的精确路径和行范围，并在 evidence 中包含能逐字对应输入材料的具体代码、
分析器消息或上下文片段。P0 仅限可被利用的关键风险；P1 是很可能的缺陷或安全问题；P2 是已确认的
低影响问题。额外代码只能使用 request_context 工具请求最小的相对路径和行范围，绝不能直接猜测或要求
完整文件。证据不足时使用该工具；若工具表示内容尚未提供，则返回 needs_context。所有报告、标题、
证据和建议必须使用中文。"""


class ModelTimeoutError(Exception):
    pass


class InvalidModelOutputError(Exception):
    pass


class ContextLimitExceededError(Exception):
    pass


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Map each changed path to added-side line numbers from unified diff hunks."""
    paths: dict[str, set[int]] = defaultdict(set)
    path: str | None = None
    new_line: int | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path, new_line = line.removeprefix("+++ b/"), None
        elif line.startswith("@@ ") and path is not None:
            plus = line.split(" +", maxsplit=1)
            try:
                new_line = int(plus[1].split(" ", maxsplit=1)[0].removeprefix("+").split(",")[0])
            except (IndexError, ValueError):
                new_line = None
        elif path is not None and new_line is not None:
            if line.startswith("+") and not line.startswith("+++"):
                paths[path].add(new_line)
                new_line += 1
            elif line.startswith(" "):
                new_line += 1
    return dict(paths)


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make generated Pydantic schemas compatible with OpenAI strict outputs."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
    for value in schema.values():
        if isinstance(value, dict):
            strict_schema(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    strict_schema(item)
    return schema


def _static_analysis_text(items: Sequence[dict[str, Any]]) -> str:
    return (
        "\n".join(
            f"- {item['tool']} {item['path']}:{item['line']}：{item['message']}" for item in items
        )
        or "（未提供）"
    )


def _context_content(request: ContextRequest, contexts: Sequence[ReviewContext]) -> str | None:
    """Return only a tool-requested subrange already provided by the client."""
    for item in contexts:
        if (
            item.path == request.path
            and item.start_line <= request.start_line <= request.end_line <= item.end_line
        ):
            lines = item.content.splitlines(keepends=True)
            selected = "".join(
                lines[request.start_line - item.start_line : request.end_line - item.start_line + 1]
            )
            if selected:
                return redact_secrets(selected)
    return None


def _function_calls(response: Any) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    for item in getattr(response, "output", []) or []:
        if isinstance(item, dict):
            item_type, name = item.get("type"), item.get("name")
            call_id, arguments = item.get("call_id"), item.get("arguments")
        else:
            item_type, name = getattr(item, "type", None), getattr(item, "name", None)
            call_id, arguments = getattr(item, "call_id", None), getattr(item, "arguments", None)
        if (
            item_type == "function_call"
            and name == "request_context"
            and isinstance(call_id, str)
            and isinstance(arguments, str)
        ):
            calls.append((call_id, arguments))
    return calls


async def run_model(
    diff: str,
    contexts: Sequence[ReviewContext],
    rules: Sequence[ReviewRule],
    static_analysis: Sequence[dict[str, Any]] = (),
) -> ReviewModelResult:
    """Send diff/rules/static analysis; code can reach the model only via the function tool."""
    api_key = getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 OpenAI 凭据")
    rules_text = (
        "\n".join(f"- {r.name}：{r.instruction}" for r in rules if r.enabled)
        or "- 无组织附加规则。"
    )
    prompt = (
        f"组织审查规则：\n{rules_text}\n\n静态分析结果（仅作证据线索，不含源代码）：\n"
        f"{_static_analysis_text(static_analysis)}\n\nGit diff：\n{redact_secrets(diff)}"
    )
    tool = {
        "type": "function",
        "name": "request_context",
        "strict": True,
        "description": "请求最小的仓库相对路径代码行范围。仅在证据不足时调用。",
        "parameters": strict_schema(ContextRequest.model_json_schema()),
    }
    text_format = {
        "type": "json_schema",
        "name": "review_result",
        "strict": True,
        "schema": strict_schema(ReviewModelResult.model_json_schema()),
    }
    client = AsyncOpenAI(api_key=api_key, base_url=getenv("OPENAI_BASE_URL") or None)
    try:
        try:
            async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
                response = await cast(Any, client.responses).create(
                    model=getenv("OPENAI_MODEL", "gpt-5"),
                    instructions=REVIEW_INSTRUCTIONS,
                    input=prompt,
                    max_output_tokens=4_000,
                    store=False,
                    tools=[tool],
                    parallel_tool_calls=False,
                    text={"format": text_format},
                )
                consumed = 0
                unavailable_requests: set[tuple[str, int, int]] = set()
                for _ in range(MAX_CONTEXT_TOOL_CALLS):
                    calls = _function_calls(response)
                    if not calls:
                        break
                    outputs: list[dict[str, str]] = []
                    for call_id, raw in calls:
                        try:
                            request = ContextRequest.model_validate_json(raw)
                        except ValidationError:
                            tool_result: dict[str, Any] = {"available": False, "reason": "请求无效"}
                        else:
                            content = _context_content(request, contexts)
                            if content is None:
                                unavailable_requests.add(
                                    (request.path, request.start_line, request.end_line)
                                )
                                tool_result = {"available": False, "reason": "内容尚未由用户提供"}
                            else:
                                size = len(content.encode())
                                if consumed + size > MAX_CONTEXT_BYTES:
                                    raise ContextLimitExceededError("获准上下文总量超过限制")
                                consumed += size
                                tool_result = {
                                    "available": True,
                                    **request.model_dump(),
                                    "content": content,
                                }
                        outputs.append(
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": json.dumps(tool_result, ensure_ascii=False),
                            }
                        )
                    response = await cast(Any, client.responses).create(
                        model=getenv("OPENAI_MODEL", "gpt-5"),
                        previous_response_id=getattr(response, "id", None),
                        input=outputs,
                        max_output_tokens=4_000,
                        store=False,
                        tools=[tool],
                        parallel_tool_calls=False,
                        text={"format": text_format},
                    )
                else:
                    raise ContextLimitExceededError("请求上下文次数超过限制")
        except TimeoutError as error:
            raise ModelTimeoutError("模型响应超时") from error
        try:
            result = ReviewModelResult.model_validate_json(response.output_text)
            if (
                result.status == "needs_context"
                and not {
                    (item.path, item.start_line, item.end_line) for item in result.requested_context
                }
                <= unavailable_requests
            ):
                raise InvalidModelOutputError("上下文请求必须来自 request_context 工具调用")
            return result
        except (AttributeError, ValidationError, ValueError) as error:
            raise InvalidModelOutputError("模型返回无效结构化输出") from error
    finally:
        await client.close()


def _evidence_sources(
    diff: str, contexts: Sequence[ReviewContext], static: Sequence[dict[str, Any]]
) -> list[str]:
    sources = [line[1:].strip() for line in diff.splitlines() if line.startswith("+")]
    sources.extend(line.strip() for item in contexts for line in item.content.splitlines())
    sources.extend(str(item.get("message", "")).strip() for item in static)
    return [source for source in sources if len(source) >= 3]


def _deduplicate_findings(findings: Sequence[Finding]) -> list[Finding]:
    merged: dict[tuple[str, int, int, str, str], Finding] = {}
    rank = {"P0": 0, "P1": 1, "P2": 2}
    for finding in findings:
        key = (
            finding.path,
            finding.start_line,
            finding.end_line,
            finding.category,
            re.sub(r"\s+", " ", finding.title).casefold(),
        )
        previous = merged.get(key)
        if previous is None:
            merged[key] = finding
            continue
        winner = finding if rank[finding.severity] < rank[previous.severity] else previous
        merged[key] = winner.model_copy(
            update={
                "evidence": "\n".join(dict.fromkeys((previous.evidence, finding.evidence))),
                "recommendation": "\n".join(
                    dict.fromkeys((previous.recommendation, finding.recommendation))
                ),
            }
        )
    return list(merged.values())


def verified_findings(
    findings: Sequence[Finding],
    diff: str,
    contexts: Sequence[ReviewContext] = (),
    static_analysis: Sequence[dict[str, Any]] = (),
) -> list[Finding]:
    """Keep high-confidence changed-line reports whose evidence literally exists in input."""
    lines_by_path, sources = changed_lines(diff), _evidence_sources(diff, contexts, static_analysis)
    anchored = [
        f
        for f in findings
        if f.confidence == "high"
        and f.path in lines_by_path
        and all(line in lines_by_path[f.path] for line in range(f.start_line, f.end_line + 1))
        and any(source in f.evidence for source in sources)
    ]
    return _deduplicate_findings(anchored)


def _failure_report(error: Exception) -> str:
    if isinstance(error, ModelTimeoutError):
        return "审查模型响应超时，请稍后重新提交。"
    if isinstance(error, InvalidModelOutputError):
        return "审查模型返回无效结果，请稍后重新提交。"
    if isinstance(error, ContextLimitExceededError):
        return "审查所需上下文超过安全限制，请缩小变更或分批提交。"
    return "审查任务执行失败，请稍后重新提交。"


async def run_review(_ctx: dict[str, Any], review_id: str) -> None:
    database = Database(cast(str | None, _ctx.get("database_url")))
    with database.sessions() as session:
        review = session.scalar(select(Review).where(Review.id == review_id))
        if review is None or not review.diff:
            return
        review.status = "running"
        session.commit()
        contexts = session.scalars(
            select(ReviewContext).where(
                ReviewContext.review_id == review.id,
                ReviewContext.organization_id == review.organization_id,
            )
        ).all()
        rules = session.scalars(
            select(ReviewRule)
            .where(ReviewRule.organization_id == review.organization_id)
            .order_by(ReviewRule.priority, ReviewRule.created_at)
        ).all()
        try:
            static = [
                StaticAnalysisFinding.model_validate(item).model_dump()
                for item in review.static_analysis
            ]
            result = await run_model(review.diff, contexts, rules, static)
            findings = verified_findings(result.findings, review.diff, contexts, static)
        except Exception as error:
            review.status, review.report = "failed", _failure_report(error)
            session.commit()
            return
        session.execute(delete(ReviewFinding).where(ReviewFinding.review_id == review.id))
        for finding in findings:
            session.add(
                ReviewFinding(
                    organization_id=review.organization_id,
                    review_id=review.id,
                    **finding.model_dump(),
                )
            )
        review.status, review.report = result.status, result.report
        review.requested_context = (
            [item.model_dump() for item in result.requested_context]
            if result.status == "needs_context"
            else []
        )
        session.commit()


class WorkerSettings:
    functions = [func(cast(WorkerCoroutine, run_review), max_tries=3)]
    redis_settings = RedisSettings.from_dsn(getenv("REDIS_URL", "redis://localhost:6379/0"))
    job_timeout = 120


def main() -> None:
    run_worker(cast(WorkerSettingsType, WorkerSettings))
