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
    content: str
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
    事件（thought/tool/confirm/progress）已在调用方过滤。
    """
    # 先按 keep_from 截断更早消息（若命中）
    if keep_from:
        for index, message in enumerate(messages):
            if message.get("source_id") == keep_from:
                messages = messages[index:]
                break
    # 再取末尾 limit 条（保持原始时间顺序）
    return messages[-limit:] if limit > 0 else []
