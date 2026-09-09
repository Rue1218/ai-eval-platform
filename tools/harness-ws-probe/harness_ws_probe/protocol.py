"""API.md §4 冻结的事件名、公共头与瞬态判定。"""

from __future__ import annotations

from typing import Any

# 前端 → 服务：仅此五条（API.md §4.4，含危险工具确认回执）
UPLINK_EVENTS = frozenset(
    {
        "user_message",
        "confirm_ack",
        "cancel_task",
        "clarify_reply",
        "tool_approval_ack",
    }
)

# 服务 → 前端：允许的事件名（§4.3，V1.78 现行词汇表 event.v5）。
# 对齐 backend/shared/event_vocab.py：PERSISTENT_KINDS = NODE_EVENT_KINDS |
# _EMITTER_ONLY_KINDS；另加瞬态帧 assistant_delta/tool_progress/
# tool_output_delta/pong。禁止旧名 thinking/token/chat:send/
# tool_call_start/message/done。
DOWNLINK_EVENTS = frozenset(
    {
        # 图节点可产出（NODE_EVENT_KINDS）
        "user_message",
        "thought",
        "tool_call",
        "tool_result",
        "confirm",
        "clarify",
        "plan",
        "task_state",
        "progress",
        "report",
        "error",
        "assistant_message",
        "response.completed",
        "fabrication",  # V1.75（P3）编造对账审计留痕（仅审计，不入正文事件）
        # 收包循环 / 标题后台 / Worker 直产（_EMITTER_ONLY_KINDS）
        "confirm_ack",
        "task_cancelled",
        "tool_approval_ack",
        "clarify_ack",  # V1.72（#1）
        "approval_terminal",  # V1.73（#3）
        "context_trim",  # V1.74（#2）
        "session_title",
        # 历史保留（无生产者或骨架化遗留，白名单兼容回放）
        "tool_approval",
        "assistant_delta",
        "tool_progress",
        "tool_output_delta",
        "pong",
    }
)

# 当前词汇表版本（API.md §4.3 V1.75 现值；增删 kind 必须递增）
EXPECTED_VOCAB_VERSION = "event.v5"

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
