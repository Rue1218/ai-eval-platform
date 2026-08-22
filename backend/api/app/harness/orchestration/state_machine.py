"""ReAct 回合状态机：只管理内部审计状态，不新增 WebSocket 事件。"""

from __future__ import annotations

from dataclasses import dataclass

from app.harness.contracts.turn import TurnStatus


class InvalidTurnTransition(ValueError):
    """状态转移不满足 ReAct 不变量，调用方必须熔断当前 Turn。"""


_ALLOWED_TRANSITIONS: dict[TurnStatus, frozenset[TurnStatus]] = {
    TurnStatus.INIT: frozenset({TurnStatus.PARSED, TurnStatus.CANCELLING, TurnStatus.FAILED_STOP}),
    TurnStatus.PARSED: frozenset(
        {
            TurnStatus.EXECUTING,
            TurnStatus.FEEDBACK_READY,
            TurnStatus.CANCELLING,
            TurnStatus.FAILED_STOP,
        }
    ),
    TurnStatus.EXECUTING: frozenset(
        {TurnStatus.FEEDBACK_READY, TurnStatus.CANCELLING, TurnStatus.FAILED_STOP}
    ),
    TurnStatus.FEEDBACK_READY: frozenset(
        {
            TurnStatus.PARSED,
            TurnStatus.CANCELLING,
            TurnStatus.FAILED_STOP,
        }
    ),
    TurnStatus.CANCELLING: frozenset({TurnStatus.CANCELLED, TurnStatus.FAILED_STOP}),
    TurnStatus.CANCELLED: frozenset(),
    TurnStatus.FINISHED: frozenset(),
    TurnStatus.FAILED_STOP: frozenset(),
}


@dataclass
class TurnStateMachine:
    """单个 Turn 的内存状态机；实例不得跨请求缓存。"""

    status: TurnStatus = TurnStatus.INIT

    def transition(self, target: TurnStatus) -> TurnStatus:
        """校验并写入下一内部状态，非法转移由上层统一归一为 INTERNAL。"""
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTurnTransition(f"非法 Turn 状态转移 {self.status} -> {target}")
        self.status = target
        return self.status


__all__ = ["InvalidTurnTransition", "TurnStateMachine", "TurnStatus"]
