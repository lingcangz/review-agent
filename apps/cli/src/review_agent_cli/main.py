import argparse
import getpass
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError

from review_agent_cli.analysis import LocalFinding, run_local_analysis
from review_agent_cli.client import ApiClient
from review_agent_cli.config import CliConfig, load_config, remember_review, save_config
from review_agent_cli.git import ReviewInput, collect_review_input
from review_agent_cli.safety import (
    is_ignored,
    normalize_repository_path,
    read_ignore_patterns,
    redact_secrets,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="提交最小化 Git diff 进行代码审阅")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="初始化仓库外的本机 CLI 配置")
    init.add_argument("--api-url", default="http://localhost:8000", help="API 地址")
    login = subparsers.add_parser("login", help="通过邮箱魔术链接登录并保存 CLI PAT")
    login.add_argument("--email", required=True, help="组织成员邮箱")
    login.add_argument("--organization", required=True, help="组织 ID")
    login.add_argument("--api-url", help="API 地址")
    login.add_argument("--name", default="review-agent CLI", help="PAT 名称")
    review = subparsers.add_parser("review", help="从指定 base 提交当前 Git diff")
    review.add_argument("--base", required=True, help="比较基准，例如 origin/main")
    review.add_argument("--api-url", help="API 地址")
    review.add_argument("--token", help="CLI Personal Access Token")
    review.add_argument(
        "--context",
        action="append",
        default=[],
        help="显式附加的上下文，格式为 路径 或 路径@起始行-结束行",
    )
    review.add_argument(
        "--confirm",
        action="store_true",
        help="提交前要求人工确认；默认自动确认 y",
    )
    review.add_argument(
        "--yes",
        action="store_true",
        help="兼容选项：默认已自动确认 y",
    )
    review.add_argument("--poll-interval", type=float, default=1.0, help="轮询间隔（秒）")
    review.add_argument("--timeout", type=float, default=120.0, help="最大等待时间（秒）")
    history = subparsers.add_parser("history", help="显示此设备保存的最近审查任务")
    history.add_argument("--limit", type=int, default=20, help="最多显示的条数")
    history.add_argument("--api-url", help="API 地址")
    history.add_argument("--token", help="CLI Personal Access Token")
    history.add_argument("--local", action="store_true", help="只显示本机历史，不访问 API")
    return parser


def _require_token(args: argparse.Namespace, config: CliConfig) -> str:
    token = args.token or os.getenv("REVIEW_AGENT_TOKEN") or config.token
    if not token:
        raise ValueError(
            "请先运行 review-agent login，或通过 --token / REVIEW_AGENT_TOKEN 提供 PAT"
        )
    return token


def _validate_input(review_input: ReviewInput) -> tuple[str, int]:
    if not review_input.files or not review_input.diff.strip():
        raise ValueError("指定 base 与当前工作区之间没有可审查的文本变更")
    patterns = read_ignore_patterns(review_input.repository_root)
    ignored = [item.path for item in review_input.files if is_ignored(item.path, patterns)]
    if ignored:
        raise ValueError(f"拒绝上传 .review-agentignore 保护的路径：{', '.join(ignored)}")
    binary = [item.path for item in review_input.files if item.binary]
    if binary:
        raise ValueError(f"拒绝上传二进制文件变更：{', '.join(binary)}")
    redacted = redact_secrets(review_input.diff)
    return redacted, int(redacted != review_input.diff)


def _confirm(review_input: ReviewInput, redacted_count: int, automatic: bool) -> None:
    print(
        f"将仅上传 {len(review_input.files)} 个文件的 Git diff 和无源代码的静态分析摘要；"
        "不会上传完整仓库。"
    )
    print("文件：" + ", ".join(item.path for item in review_input.files))
    if redacted_count:
        print("检测到密钥模式，相关值已在上传前脱敏。")
    if automatic:
        print("已自动确认 y 并提交。")
        return
    if not sys.stdin.isatty():
        raise ValueError("非交互环境必须显式传入 --yes 才能提交")
    answer = input("确认提交以上脱敏 diff 到审查 API？[y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise ValueError("已取消提交")


def _read_context_range(
    path: Path, relative: str, start_line: int = 1, end_line: int | None = None
) -> dict[str, str | int]:
    if start_line < 1 or (end_line is not None and end_line < start_line):
        raise ValueError("上下文行范围无效")
    raw = path.read_text(encoding="utf-8")
    if "\x00" in raw:
        raise ValueError(f"拒绝回传二进制上下文：{relative}")
    lines = raw.splitlines(keepends=True)
    selected = lines[start_line - 1 : end_line]
    if not selected:
        raise ValueError(f"请求的上下文行范围为空：{relative}")
    selected_end = start_line + len(selected) - 1
    if selected_end - start_line >= 500:
        raise ValueError("单个上下文范围最多 500 行")
    return {
        "path": relative,
        "start_line": start_line,
        "end_line": selected_end,
        "content": redact_secrets("".join(selected)),
    }


def _repository_file(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"拒绝回传仓库外的上下文：{relative}") from error
    if not path.is_file():
        raise ValueError(f"上下文文件不存在：{relative}")
    return path


def _context_for_request(root: Path, requested_paths: object) -> list[dict[str, str | int]]:
    if not isinstance(requested_paths, list):
        raise ValueError("服务请求了无效的上下文路径")
    patterns = read_ignore_patterns(root)
    context: list[dict[str, str | int]] = []
    for value in requested_paths:
        if not isinstance(value, dict):
            raise ValueError("服务请求了无效的上下文路径")
        raw_path = value.get("path")
        start_line = value.get("start_line")
        end_line = value.get("end_line")
        if (
            not isinstance(raw_path, str)
            or not isinstance(start_line, int)
            or not isinstance(end_line, int)
        ):
            raise ValueError("服务请求了无效的上下文行范围")
        relative = normalize_repository_path(raw_path)
        if is_ignored(relative, patterns):
            raise ValueError(f"拒绝回传受保护的上下文：{relative}")
        path = _repository_file(root, relative)
        context.append(_read_context_range(path, relative, start_line, end_line))
    return context


def _initial_context(root: Path, specifications: list[str]) -> list[dict[str, str | int]]:
    patterns = read_ignore_patterns(root)
    context: list[dict[str, str | int]] = []
    for specification in specifications:
        path_text, separator, range_text = specification.rpartition("@")
        relative = normalize_repository_path(path_text if separator else specification)
        if is_ignored(relative, patterns):
            raise ValueError(f"拒绝上传 .review-agentignore 保护的上下文：{relative}")
        start_line, end_line = 1, None
        if separator:
            try:
                start_text, end_text = range_text.split("-", 1)
                start_line, end_line = int(start_text), int(end_text)
            except ValueError as error:
                raise ValueError("上下文行范围应为 路径@起始行-结束行") from error
        path = _repository_file(root, relative)
        context.append(_read_context_range(path, relative, start_line, end_line))
    return context


def _poll_review(
    client: ApiClient, review_id: str, root: Path, interval: float, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        result = client.request("GET", f"/v1/reviews/{review_id}")
        status = result.get("status")
        if status == "needs_context":
            context = _context_for_request(root, result.get("requested_context"))
            if not context:
                raise ValueError("服务请求上下文但未给出路径")
            client.request("POST", f"/v1/reviews/{review_id}/context", {"context": context})
            continue
        if status in {"completed", "failed"}:
            return result
        if time.monotonic() >= deadline:
            raise ValueError(f"审查任务仍在 {status or '未知'} 状态；可稍后用 history 查询任务 ID")
        time.sleep(max(interval, 0.1))


def _print_findings(findings: list[LocalFinding]) -> None:
    if not findings:
        return
    print("本地高置信检查（未上传）：")
    for finding in findings:
        print(f"- {finding.tool} {finding.path}:{finding.line}：{finding.message}")


def _static_analysis_payload(
    root: Path, findings: list[LocalFinding]
) -> list[dict[str, str | int]]:
    """Convert local analyzer locations to safe repository-relative API metadata."""
    payload: list[dict[str, str | int]] = []
    for finding in findings:
        source = Path(finding.path)
        try:
            relative = (
                source.resolve().relative_to(root.resolve()).as_posix()
                if source.is_absolute()
                else normalize_repository_path(finding.path)
            )
        except ValueError:
            continue
        payload.append(
            {
                "tool": finding.tool,
                "path": relative,
                "line": finding.line,
                "message": finding.message,
            }
        )
    return payload


def run_init(args: argparse.Namespace) -> None:
    config = load_config()
    config.api_url = args.api_url.rstrip("/")
    save_config(config)
    print("CLI 配置已初始化；配置与令牌不会写入当前仓库。")


def run_login(args: argparse.Namespace) -> None:
    config = load_config()
    api_url = (args.api_url or config.api_url).rstrip("/")
    client = ApiClient(api_url)
    client.request(
        "POST",
        "/v1/auth/email-login",
        {"email": args.email, "organization_id": args.organization},
    )
    one_time_token = getpass.getpass("请输入邮件中的一次性登录令牌：")
    verified = client.request(
        "POST",
        "/v1/auth/email-login/verify",
        {"email": args.email, "organization_id": args.organization, "token": one_time_token},
    )
    access_token = verified.get("access_token")
    if not isinstance(access_token, str):
        raise ValueError("登录服务未返回访问令牌")
    pat = ApiClient(api_url, access_token).request(
        "POST", "/v1/auth/personal-access-tokens", {"name": args.name}
    )
    saved_token = pat.get("token")
    if not isinstance(saved_token, str):
        raise ValueError("服务未返回 CLI PAT")
    config.api_url = api_url
    config.token = saved_token
    save_config(config)
    print("登录成功，CLI PAT 已安全保存到当前用户配置。")


def run_review(args: argparse.Namespace) -> None:
    config = load_config()
    review_input = collect_review_input(Path.cwd(), args.base)
    redacted_diff, redacted_count = _validate_input(review_input)
    initial_context = _initial_context(review_input.repository_root, args.context)
    _confirm(review_input, redacted_count, not args.confirm)
    local_findings = run_local_analysis(review_input.repository_root, review_input.files)
    token = _require_token(args, config)
    client = ApiClient((args.api_url or config.api_url).rstrip("/"), token)
    created = client.request(
        "POST",
        "/v1/reviews",
        {
            "diff": redacted_diff,
            "context": initial_context,
            "static_analysis": _static_analysis_payload(
                review_input.repository_root, local_findings
            ),
        },
    )
    review_id = created.get("review_id")
    if not isinstance(review_id, str):
        raise ValueError("服务未返回审查任务 ID")
    remember_review(config, review_id, args.base, str(created.get("status", "queued")))
    save_config(config)
    result = _poll_review(
        client, review_id, review_input.repository_root, args.poll_interval, args.timeout
    )
    remember_review(config, review_id, args.base, str(result.get("status", "unknown")))
    save_config(config)
    report = result.get("report")
    if isinstance(report, str):
        print(report)
    findings = result.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                print(
                    f"[{finding.get('severity', 'P?')}] {finding.get('path', '?')}:"
                    f"{finding.get('start_line', '?')} {finding.get('title', '')}"
                )
    _print_findings(local_findings)


def run_history(args: argparse.Namespace) -> None:
    config = load_config()
    token = args.token or os.getenv("REVIEW_AGENT_TOKEN") or config.token
    if token and not args.local:
        try:
            limit = min(max(args.limit, 1), 100)
            result = ApiClient((args.api_url or config.api_url).rstrip("/"), token).request(
                "GET", f"/v1/reviews?limit={limit}"
            )
            items = result.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        print(
                            f"{item.get('created_at', '')}\t{item.get('status', '')}\t"
                            f"远端\t{item.get('review_id', '')}"
                        )
                return
        except (URLError, ValueError):
            print("远端历史暂不可用，显示本机记录。", file=sys.stderr)
    for entry in config.history[: max(args.limit, 0)]:
        print(f"{entry.created_at}\t{entry.status}\t{entry.base}\t{entry.review_id}")


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            run_init(args)
        elif args.command == "login":
            run_login(args)
        elif args.command == "review":
            run_review(args)
        elif args.command == "history":
            run_history(args)
    except (OSError, UnicodeError, ValueError, URLError, subprocess.CalledProcessError) as error:
        print(f"审阅失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
