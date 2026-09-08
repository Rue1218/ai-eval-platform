"""事件检查传输层专用的向外脱敏。

追加式事实日志仍是内部审计来源。REST 与 WebSocket 消费者收到独立副本，
用于学习的事件轨迹既能展示数据包形状，也不会泄露模型、工具或未来扩展提供的凭据。
"""

from __future__ import annotations

import re
from typing import Any

from app.harness.contracts.loop_events import sensitive_paths_for_event_type

REDACTED = "[已脱敏]"

# 只匹配承载凭据的“字段名”，刻意不匹配 ``prompt_tokens``、``tokenizer``
# 这类无害的观测字段。
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?key|cookie|password|"
    r"private[_-]?key|secret|credential|bearer|(?:^|[_-])token(?:$|[_-]))",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:\bbearer\s+[a-z0-9._~+/=-]{8,}|\bsk-[a-z0-9._-]{8,})",
    re.IGNORECASE,
)


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        return ()
    return tuple(
        part.replace("~1", "/").replace("~0", "~")
        for part in pointer[1:].split("/")
    )


def _path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    """匹配精确 JSON Pointer 路径，``*`` 仅表示一个路径片段。"""

    path_parts = _pointer_parts(path)
    for pattern in patterns:
        pattern_parts = _pointer_parts(pattern)
        if pattern_parts and len(path_parts) == len(pattern_parts) and all(
            expected == "*" or expected == actual
            for expected, actual in zip(pattern_parts, path_parts, strict=True)
        ):
            return True
    return False


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key))


def redact_for_transport(
    value: Any,
    *,
    sensitive_paths: tuple[str, ...] = (),
    _path: str = "",
) -> Any:
    """返回可 JSON 序列化的深拷贝，并替换已知的凭据值。"""

    if _path and _path_matches(_path, sensitive_paths):
        return REDACTED
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{_path}/{_pointer_escape(key_text)}"
            safe[key_text] = (
                REDACTED
                if _is_sensitive_key(key_text)
                else redact_for_transport(
                    item,
                    sensitive_paths=sensitive_paths,
                    _path=child_path,
                )
            )
        return safe
    if isinstance(value, list):
        return [
            redact_for_transport(
                item,
                sensitive_paths=sensitive_paths,
                _path=f"{_path}/{index}",
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return REDACTED
    return value


def redact_event_for_transport(event: dict[str, Any]) -> dict[str, Any]:
    """按事件类型注册的策略，对持久事件信封进行脱敏。"""

    event_type = event.get("type")
    paths = sensitive_paths_for_event_type(event_type) if isinstance(event_type, str) else ()
    return redact_for_transport(event, sensitive_paths=paths)


def redact_frame_for_transport(frame: dict[str, Any]) -> dict[str, Any]:
    """不改写源数据，对所有服务端至浏览器的帧进行脱敏。

    ``trace_event`` 与 ``history`` 将持久事件信封放在传输帧的下一层，
    所以事件专属 JSON Pointer 必须在正确的根节点应用；其余帧仍按敏感字段名脱敏。
    """

    frame_type = frame.get("type")
    if frame_type == "trace_event" and isinstance(frame.get("event"), dict):
        safe = redact_for_transport(frame)
        safe["event"] = redact_event_for_transport(frame["event"])
        return safe
    if frame_type == "history" and isinstance(frame.get("events"), list):
        safe = redact_for_transport(frame)
        safe["events"] = [
            redact_event_for_transport(event) if isinstance(event, dict) else event
            for event in frame["events"]
        ]
        return safe
    return redact_for_transport(frame)
