"""Harness 上下文工程层：最近消息窗口算法（M2 阶段 1，CX-1/CX-2）。

最近消息窗口是**唯一**窗口算法：默认取末尾 20 条 user/assistant 消息，
``compact_keep_from`` 指定保留起点时截断更早消息。思考/工具/确认/进度事件
不进消息窗口，只入 ws_events 供回放（CX-2，调用方按 role 过滤后传入）。
"""

from __future__ import annotations

from typing import TypedDict


class WindowMessage(TypedDict, total=False):
    """窗口内消息的最小投影；只含 user/assistant。"""

    role: str  # "user" | "assistant"
    content: object
    source_id: str | None


def is_window_eligible(role: str) -> bool:
    """仅 user/assistant 进窗口（CX-2）。"""
    return role in ("user", "assistant")


def recent_window(
    messages: list[WindowMessage],
    *,
    limit: int = 20,
    keep_from: str | None = None,
) -> list[WindowMessage]:
    """唯一窗口算法：取末尾 limit 条 user/assistant 消息。

    ``keep_from``（compact_keep_from）指定保留起点 source_id 时，截断该起点
    之前的消息；起点本身不在列表中时忽略该参数（原始记录保留在 DB，不删除）。
    本函数再按 ``is_window_eligible`` 过滤一遍（CX-2 纵深防御）。
    """
    windowed, _meta = window_trim_stats(messages, limit=limit, keep_from=keep_from)
    return windowed


def window_trim_stats(
    messages: list[WindowMessage],
    *,
    limit: int = 20,
    keep_from: str | None = None,
) -> tuple[list[WindowMessage], dict[str, object]]:
    """唯一窗口算法同源实现 + 裁剪元信息（#2 上下文压缩事件化留痕用）。

    返回 ``(窗口消息, meta)``；``meta`` 字段：``reason``（compact = keep_from
    截断命中；tail_window = 末 N 条尾窗截断）、``dropped``（本次裁剪条数）、
    ``kept``、``in_scope_total``（可入窗消息总数）、``keep_from_id``、``limit``。
    未发生裁剪时 ``dropped=0``（调用方据此决定是否留痕，避免无裁剪也发事件）。
    仅记录元信息——不携带被裁消息原文（观察纪律：正文不进事件/检查点）。
    """
    eligible = [
        message
        for message in messages
        if is_window_eligible(str(message.get("role") or ""))
    ]
    in_scope_total = len(eligible)
    kept_from_id: str | None = None
    # 先按 keep_from 截断更早消息（若命中）
    if keep_from:
        for index, message in enumerate(eligible):
            if message.get("source_id") == keep_from:
                kept_from_id = keep_from
                eligible = eligible[index:]
                break
    # 再取末尾 limit 条（保持原始时间顺序）
    windowed = eligible[-limit:] if limit > 0 else []
    kept = len(windowed)
    reason = "compact" if kept_from_id else "tail_window"
    return windowed, {
        "reason": reason,
        "dropped": max(0, in_scope_total - kept),
        "kept": kept,
        "in_scope_total": in_scope_total,
        "keep_from_id": kept_from_id,
        "limit": limit,
    }
