"""最终回复交付状态：正文读取仍由 ``harness.llm`` 唯一正文负责。"""

from __future__ import annotations

from app.harness.contracts.trace import TraceContext
from app.harness.contracts.turn import TurnStatus
from app.harness.feedback.publisher import publisher


def begin_finalizing_delivery(*, trace: TraceContext) -> None:
    """在最终助手消息真正交付前进入收尾；外层只在消息持久化成功后结束 Turn。"""
    publisher().set_turn_status(trace, status=TurnStatus.FINALIZING_STREAM)
