"""arq worker that sends only bounded, redacted review input to OpenAI."""

from collections import defaultdict
from collections.abc import Sequence
from os import getenv
from typing import Any, cast

from arq.connections import RedisSettings
from arq.typing import WorkerCoroutine, WorkerSettingsType
from arq.worker import func, run_worker
from openai import AsyncOpenAI
from sqlalchemy import delete, select

from review_agent_api.database import Database
from review_agent_api.db_models import Review, ReviewContext, ReviewFinding, ReviewRule
from review_agent_api.models import Finding, ReviewModelResult
from review_agent_api.privacy import redact_secrets

REVIEW_INSTRUCTIONS = """你是团队 Python Git 变更审阅器。仅报告可由提交 diff 或获准上下文证实的：
1. 正确性缺陷；2. 安全漏洞；3. 此次变更直接造成的回归。
不要报告风格、重构建议、猜测或低置信度问题。每条 finding 必须定位到改动后的精确路径和行范围，
并给出提交中的具体证据。P0 仅限可被利用的关键风险；P1 是很可能的缺陷或安全问题；
P2 是已确认的低影响问题。证据不足时返回 needs_context，并只请求最小的相对路径和行范围上下文。
所有报告、标题、证据和建议必须使用中文。"""


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Map each changed path to added-side line numbers from unified diff hunks."""
    paths: dict[str, set[int]] = defaultdict(set)
    path: str | None = None
    new_line: int | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line.removeprefix("+++ b/")
            new_line = None
        elif line.startswith("@@ ") and path is not None:
            plus = line.split(" +", maxsplit=1)
            if len(plus) != 2:
                new_line = None
                continue
            position = plus[1].split(" ", maxsplit=1)[0].removeprefix("+")
            new_line = int(position.split(",", maxsplit=1)[0])
        elif path is not None and new_line is not None:
            if line.startswith("+") and not line.startswith("+++"):
                paths[path].add(new_line)
                new_line += 1
            elif line.startswith(" "):
                new_line += 1
    return dict(paths)


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make the Pydantic JSON Schema compatible with strict Structured Outputs."""
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


async def run_model(
    diff: str, contexts: Sequence[ReviewContext], rules: Sequence[ReviewRule]
) -> ReviewModelResult:
    api_key = getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 OpenAI 凭据")
    context_text = "\n\n".join(
        f"--- 路径：{item.path}（原文件第 {item.start_line}-{item.end_line} 行）\n"
        f"{redact_secrets(item.content)}"
        for item in contexts
    )
    rule_text = (
        "\n".join(f"- {rule.name}：{rule.instruction}" for rule in rules if rule.enabled)
        or "- 无组织附加规则。"
    )
    prompt = (
        f"组织审查规则：\n{rule_text}\n\n"
        f"Git diff：\n{redact_secrets(diff)}\n\n"
        f"获准上下文：\n{context_text or '（未提供）'}"
    )
    client = AsyncOpenAI(api_key=api_key, base_url=getenv("OPENAI_BASE_URL") or None)
    try:
        response = await client.responses.create(
            model=getenv("OPENAI_MODEL", "gpt-5"),
            instructions=REVIEW_INSTRUCTIONS,
            input=prompt,
            max_output_tokens=4_000,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "review_result",
                    "strict": True,
                    "schema": strict_schema(ReviewModelResult.model_json_schema()),
                }
            },
        )
        return ReviewModelResult.model_validate_json(response.output_text)
    finally:
        await client.close()


def verified_findings(findings: list[Finding], diff: str) -> list[Finding]:
    lines_by_path = changed_lines(diff)
    return [
        finding
        for finding in findings
        if finding.path in lines_by_path
        and finding.start_line in lines_by_path[finding.path]
        and finding.end_line in lines_by_path[finding.path]
        and finding.evidence.strip()
    ]


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
            select(ReviewRule).where(ReviewRule.organization_id == review.organization_id)
        ).all()
        try:
            result = await run_model(review.diff, contexts, rules)
            findings = verified_findings(result.findings, review.diff)
        except Exception:
            review.status = "failed"
            review.report = "审查任务执行失败，请稍后重新提交。"
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
        review.status = result.status
        review.report = result.report
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
