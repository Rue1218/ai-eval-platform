"""取消令牌：用户停止 / 断线后在 100ms 调度预算内传播到本地 task 与 MCP。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

DEFAULT_PROPAGATION_BUDGET_MS = 100


class TurnCancelled(Exception):
    """当前 Turn 已被取消；编排层应转入 CANCELLING，不得再调模型或执行新工具。"""


@dataclass
class CancellationToken:
    """与前端 /stop、会话关闭或连接断开绑定的取消令牌。"""

    turn_id: str
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str | None = None
    requested_at_monotonic: float | None = None
    propagation_budget_ms: int = DEFAULT_PROPAGATION_BUDGET_MS

    def request(self, reason: str) -> None:
        """原子置位取消；重复调用保持首次 reason 与时间戳。"""
        if self.cancelled.is_set():
            return
        self.reason = reason
        self.requested_at_monotonic = time.monotonic()
        self.cancelled.set()

    def is_cancelled(self) -> bool:
        """是否已收到取消信号。"""
        return self.cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        """已取消则抛出 TurnCancelled，供 await 点快速退出。"""
        if self.cancelled.is_set():
            raise TurnCancelled(self.reason or "cancelled")

    def dispatch_latency_ms(self) -> float | None:
        """从请求取消到当前时刻的本地调度耗时；未请求时返回 None。"""
        if self.requested_at_monotonic is None:
            return None
        return (time.monotonic() - self.requested_at_monotonic) * 1000.0
