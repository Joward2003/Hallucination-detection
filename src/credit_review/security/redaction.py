"""Best-effort log/model redaction. It never mutates the caller's object."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*[^\s,;]+")


def redact_text(value: str) -> str:
    return _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def redact_mapping(value: Mapping[str, Any], sensitive_keys: set[str] | None = None) -> dict[str, Any]:
    keys = {"api_key", "apikey", "token", "secret", "password"} | (sensitive_keys or set())
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in keys:
            result[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            result[key] = redact_mapping(item, sensitive_keys)
        elif isinstance(item, str):
            result[key] = redact_text(item)
        else:
            result[key] = item
    return result
