"""Ensure secrets do not leave the service in a model prompt."""

import re

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s'\"]+"),
)
REDACTED = "[已脱敏]"


def redact_secrets(content: str) -> str:
    redacted = content
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted
