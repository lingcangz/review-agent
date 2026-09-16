import fnmatch
import re
from pathlib import Path, PurePosixPath

REDACTED = "[已脱敏]"
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        r"(?i)(\b(?:api[_-]?key|access[_-]?token|token|password|secret)\b\s*[:=]\s*)"
        r"(?:['\"][^'\"]+['\"]|[^\s'\"]+)"
    ),
)


def read_ignore_patterns(repository_root: Path) -> list[str]:
    ignore_file = repository_root / ".review-agentignore"
    if not ignore_file.is_file():
        return []
    return [
        line.strip()
        for line in ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def normalize_repository_path(path: str) -> str:
    """Return the POSIX relative spelling required by the API on every OS."""
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts or normalized in {"", "."}:
        raise ValueError("路径必须位于当前 Git 仓库内")
    return candidate.as_posix()


def _matches_pattern(path: str, pattern: str) -> bool:
    pattern = pattern.lstrip("/")
    if pattern.endswith("/"):
        return path == pattern[:-1] or path.startswith(pattern)
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(part, pattern) for part in path.split("/"))
    return fnmatch.fnmatchcase(path, pattern)


def is_ignored(path: str, patterns: list[str]) -> bool:
    """Apply the small, useful gitignore-compatible subset used by this product."""
    normalized = normalize_repository_path(path)
    ignored = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        if pattern and _matches_pattern(normalized, pattern):
            ignored = not negated
    return ignored


def redact_secrets(content: str) -> str:
    redacted = content
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def contains_secrets(content: str) -> bool:
    return redact_secrets(content) != content


def changed_paths(diff: str) -> list[str]:
    """Extract both sides of a textual Git diff, including deleted files."""
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            paths.append(normalize_repository_path(line.removeprefix("--- a/").split("\t", 1)[0]))
        elif line.startswith("+++ b/"):
            paths.append(normalize_repository_path(line.removeprefix("+++ b/").split("\t", 1)[0]))
    return list(dict.fromkeys(paths))
