"""脱敏：traces 不得写入 Cookie、ticket、API Key、完整提示词。"""

from __future__ import annotations

from typing import Any

_SECRET_KEYS = frozenset(
    {
        "ticket",
        "cookie",
        "authorization",
        "api_key",
        "encrypted_key",
        "password",
        "system",
        "system_prompt",
        "prompt",
    }
)


def redact(value: Any) -> Any:
    """递归替换敏感键，保留事件名与结构便于断言。"""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                cleaned[key] = "<redacted>"
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
