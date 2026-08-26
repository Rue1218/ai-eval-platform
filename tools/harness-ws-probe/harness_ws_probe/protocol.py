"""API.md §4 冻结的事件名、公共头与瞬态判定。"""

from __future__ import annotations

from typing import Any

# 前端 → 服务：仅此四条（API.md §4.4）
UPLINK_EVENTS = frozenset(
    {"user_message", "confirm_ack", "cancel_task", "clarify_reply"}
)

# 服务 → 前端：允许的事件名（§4.3）。禁止旧名 thinking/token/chat:send/message/done。
DOWNLINK_EVENTS = frozenset(
    {
        "thought",
        "user_message",
        "assistant_delta",
        "assistant_message",
        "response.completed",
        "tool_call",
        "tool_result",
        "clarify",
        "plan",
        "confirm",
        "confirm_ack",
        "progress",
        "report",
        "error",
        "pong",
    }
)

FORBIDDEN_DOWNLINK = frozenset({"thinking", "token", "chat:send", "message", "done"})

PUBLIC_HEADER_KEYS = ("event", "session_id", "task_id", "event_id", "ts", "payload")

CLOSE_TICKET = 4401
CLOSE_SESSION = 4404


def is_transient(frame: dict[str, Any]) -> bool:
    """瞬态帧不落库、不占单调事件号，前端不去重推进 last_event_id。"""
    event = frame.get("event")
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
    if event in {"pong", "assistant_delta"}:
        return True
    return event == "thought" and payload.get("stream") == "think"
