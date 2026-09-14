import argparse
import json
import sys
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from review_agent_cli.safety import changed_paths, is_ignored, read_ignore_patterns, redact_secrets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="提交最小化 Git diff 进行代码审阅")
    subparsers = parser.add_subparsers(dest="command", required=True)
    review = subparsers.add_parser("review", help="提交 diff 和显式选择的上下文")
    review.add_argument("--diff-file", type=Path, required=True, help="Git diff 文件")
    review.add_argument("--context", type=Path, action="append", default=[], help="按需上传的文件")
    review.add_argument("--api-url", default="http://localhost:8000", help="API 地址")
    review.add_argument("--organization", default="local", help="组织标识")
    return parser


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def request_review(args: argparse.Namespace, repository_root: Path) -> dict[str, object]:
    diff = args.diff_file.read_text(encoding="utf-8")
    patterns = read_ignore_patterns(repository_root)
    paths_to_check = changed_paths(diff)
    context: list[dict[str, str]] = []

    for file_path in args.context:
        path = relative_path(file_path, repository_root)
        paths_to_check.append(path)
        context.append(
            {"path": path, "content": redact_secrets(file_path.read_text(encoding="utf-8"))}
        )

    ignored = [path for path in paths_to_check if is_ignored(path, patterns)]
    if ignored:
        raise ValueError(f"拒绝上传受保护的路径：{', '.join(ignored)}")

    payload = {
        "organization_id": args.organization,
        "diff": redact_secrets(diff),
        "context": context,
    }
    request = Request(
        f"{args.api_url.rstrip('/')}/v1/reviews",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("服务返回了无效的审阅结果")
    return cast(dict[str, object], parsed)


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = request_review(args, Path.cwd())
    except (OSError, ValueError, HTTPError, URLError) as error:
        print(f"审阅失败：{error}", file=sys.stderr)
        return 1

    report = result.get("report")
    if isinstance(report, str):
        print(report)
    findings = result.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            print(json.dumps(finding, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
