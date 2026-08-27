"""API.md §4 冻结的事件名、公共头与瞬态判定。"""

from __future__ import annotations

from typing import Any

# 前端 → 服务：仅此四条（API.md §4.4）
UPLINK_EVENTS = frozenset(
    {"user_message", "confirm_ack", "cancel_task", "clarify_reply"}
)

# 服务 → 前端：允许的事件名（§4.3）。禁止旧名 thinking/token/chat:send/tool_call_start/message/done。
DOWNLINK_EVENTS = frozenset(
    {
        "thought",
        "user_message",
        "assistant_delta",
        "assistant_message",
        "response.completed",
        "tool_call",
        "tool_progress",
        "tool_output_delta",
        "tool_result",
        "clarify",
        "plan",
        "task_state",
        "confirm",
        "confirm_ack",
        "progress",
        "report",
        "error",
        "pong",
    }
)

FORBIDDEN_DOWNLINK = frozenset(
    {"thinking", "token", "chat:send", "tool_call_start", "message", "done"}
)

PUBLIC_HEADER_KEYS = ("event", "session_id", "task_id", "event_id", "ts", "payload")

CLOSE_TICKET = 4401
CLOSE_SESSION = 4404

# 不落库、不占 event_id、断线不补发的瞬态帧（API.md §4.3）：
# 助手正文增量、工具进度与工具输出增量、思考增量（stream=think）。
_TRANSIENT_EVENTS = frozenset(
    {"pong", "assistant_delta", "tool_progress", "tool_output_delta"}
)


def is_transient(frame: dict[str, Any]) -> bool:
    """瞬态帧不落库、不占单调事件号，前端不去重推进 last_event_id。"""
    event = frame.get("event")
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
    if event in _TRANSIENT_EVENTS:
        return True
    return event == "thought" and payload.get("stream") == "think"
