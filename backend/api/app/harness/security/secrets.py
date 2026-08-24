"""Harness 跨层安全：递归脱敏（M8 阶段 2，CX-3 + §5.2.1）。

``redact`` 递归遍历 dict/list，命中敏感键集合的值按方式抹除（api_key/token
保留前 4 + ``***``，password/secret/cookie 全量 ``***``）；``redact_for_log``
日志专用更严格（疑似密钥全量 ``***``）。纯函数、无副作用，供 M2（observation
注入前）、M5（dispatch 日志）、M6（归一）、ws.py（事件 payload）调用。
"""

from __future__ import annotations

from typing import Any

# 脱敏键集合（大小写不敏感匹配；M8-D5 五类 + authorization 头）
REDACT_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "cookie",
        "set-cookie",
        "authorization",
    }
)

# 全量抹除的键（password/secret/cookie/authorization 不留部分）
_FULL_MASK_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "cookie",
        "set-cookie",
        "authorization",
    }
)


def is_sensitive_key(key: str) -> bool:
    """判定键是否敏感（大小写不敏感）。"""
    return key.strip().lower() in REDACT_KEYS


def mask_partial(value: str, keep: int = 4) -> str:
    """部分保留脱敏：保留前 keep 字符 + '***'（用于 api_key/token）。"""
    if not value:
        return "***"
    return value[:keep] + "***"


def mask_full(_value: str) -> str:
    """全量脱敏：返回 '***'（用于 password/secret/cookie）。"""
    return "***"


def _mask_value(key: str, value: str) -> str:
    """按键类型选择脱敏方式。"""
    if key.strip().lower() in _FULL_MASK_KEYS:
        return mask_full(value)
    return mask_partial(value)


def redact(obj: Any) -> Any:
    """递归脱敏（CX-3）：遍历 dict/list，命中 REDACT_KEYS 的值按方式抹除。

    纯函数，返回脱敏后的副本；非密钥键原样保留。
    """
    if isinstance(obj, dict):
        return {
            key: (
                _mask_value(str(key), str(value))
                if is_sensitive_key(str(key)) and not isinstance(value, dict | list)
                else redact(value)
            )
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(redact(item) for item in obj)
    return obj


def redact_for_log(obj: Any) -> Any:
    """日志专用脱敏（§5.2.1）：更严格，所有疑似密钥全量 '***'。

    供 agent_trace / logger 调用；与 ``redact`` 的区别：不留部分前缀。
    """
    if isinstance(obj, dict):
        return {
            key: (
                mask_full(str(value))
                if is_sensitive_key(str(key)) and not isinstance(value, dict | list)
                else redact_for_log(value)
            )
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact_for_log(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(redact_for_log(item) for item in obj)
    return obj
