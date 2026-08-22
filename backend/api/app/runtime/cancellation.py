"""跨层取消契约：模型流、编排回合和执行任务共用。"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

DEFAULT_PROPAGATION_BUDGET_MS = 100


class TurnCancelled(Exception):
    """当前调用已取消；上层不得继续发起模型请求或工具执行。"""


@dataclass
class CancellationToken:
    """同时覆盖 asyncio 协程和同步线程的取消令牌。"""

    turn_id: str
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    reason: str | None = None
    requested_at_monotonic: float | None = None
    propagation_budget_ms: int = DEFAULT_PROPAGATION_BUDGET_MS

    def request(self, reason: str) -> None:
        """原子置位取消；重复请求保留第一次原因和时间戳。"""
        if self.cancelled.is_set() or self.stop.is_set():
            return
        self.reason = reason
        self.requested_at_monotonic = time.monotonic()
        self.cancelled.set()
        self.stop.set()

    def is_cancelled(self) -> bool:
        """判断协程事件或线程事件是否任一已置位。"""
        return self.cancelled.is_set() or self.stop.is_set()

    def raise_if_cancelled(self) -> None:
        """已取消时抛出统一异常，供模型读流快速退出。"""
        if self.is_cancelled():
            raise TurnCancelled(self.reason or "cancelled")

    def dispatch_latency_ms(self) -> float | None:
        """返回从取消请求到当前时刻的本地调度耗时。"""
        if self.requested_at_monotonic is None:
            return None
        return (time.monotonic() - self.requested_at_monotonic) * 1000.0
