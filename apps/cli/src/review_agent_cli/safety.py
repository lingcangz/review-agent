import fnmatch
import re
from pathlib import Path, PurePosixPath

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s'\"]+"),
)
REDACTED = "[已脱敏]"


def read_ignore_patterns(repository_root: Path) -> list[str]:
    ignore_file = repository_root / ".review-agentignore"
    if not ignore_file.is_file():
        return []
    return [
        line.strip()
        for line in ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def is_ignored(path: str, patterns: list[str]) -> bool:
    normalized = PurePosixPath(path).as_posix()
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def redact_secrets(content: str) -> str:
    redacted = content
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def changed_paths(diff: str) -> list[str]:
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line.removeprefix("+++ b/"))
    return paths
