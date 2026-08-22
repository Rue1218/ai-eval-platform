"""最终回复流式状态：字节读取仍由 ``harness.llm`` 唯一正文负责。"""

from __future__ import annotations

from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.trace import TraceContext
from app.harness.contracts.turn import TurnStatus
from app.harness.feedback.publisher import publisher
from app.harness.orchestration.state_machine import TurnStateMachine


def begin_finalizing_stream(
    *,
    trace: TraceContext,
    cancel: CancellationToken,
    state: TurnStateMachine,
) -> None:
    """进入最终交付前的流式收尾状态；取消后绝不再标记 FINISHED。"""
    cancel.raise_if_cancelled()
    state.transition(TurnStatus.FINALIZING_STREAM)
    publisher().set_turn_status(trace, status=TurnStatus.FINALIZING_STREAM)
