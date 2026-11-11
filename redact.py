"""Redact secrets in text that is shown, never in arguments that are replayed."""

from __future__ import annotations

import re
from typing import Any

_ASSIGNED = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password|passwd|authorization|bearer)\b\s*[:=]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-+/=]{8,}")
_KEYISH = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)
_MAX = 500
_SENSITIVE_KEY = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|secret|token|password|passwd|authorization|credential)"
)


def redact_text(value: str) -> str:
    text = _ASSIGNED.sub(r"\1=[REDACTED]", value)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _KEYISH.sub("[REDACTED]", text)
    if len(text) > _MAX:
        return text[:_MAX] + "…"
    return text


def redact(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]" if value not in ("", None) else value
    if isinstance(value, list):
        return [redact(item) for item in value[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_text(str(value))
