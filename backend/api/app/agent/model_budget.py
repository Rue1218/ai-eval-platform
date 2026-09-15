"""前台同进程协作的共享模型调用上限；不声称提供持久账本或金额硬预算。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.llm.loop_contracts import LlmAdapter, LlmRequest, LlmRequestError, StreamChunk


class ModelCallBudget:
    """主运行与子运行共享累计调用和并发限制，每次重试也占用调用额度。"""

    def __init__(self, *, max_calls: int, max_concurrent: int, max_calls_per_run: int):
        """只接受可精确执行的调用次数限额；token/费用预留由后续持久账本负责。"""
        if any(type(value) is not int or value < 1 for value in (
            max_calls, max_concurrent, max_calls_per_run,
        )):
            raise ValueError("模型调用与并发上限必须是正整数")
        self._max_calls = max_calls
        self._per_run = max_calls_per_run
        self._capacity = asyncio.Semaphore(max_concurrent)
        self._calls: dict[str, int] = {}
        self._total = 0
        self._active = 0
        self._closed = False

    def snapshot(self) -> dict:
        """只返回独立的计数快照，不包含提示词、响应或模型凭据。"""
        return {"calls": self._total, "active": self._active, "by_run": dict(self._calls)}

    def close(self) -> None:
        """阻止新的调用；已派发调用仍由运行时取消并结算，不返还未知消耗。"""
        self._closed = True

    def _admit(self, run_id: str) -> None:
        """同一事件循环内无 await 地检查并扣减，避免并发通过最后一份额度。"""
        if self._closed:
            raise LlmRequestError("协作已结束", code="collaboration_closed", public_code="CONCURRENCY")
        if self._total >= self._max_calls or self._calls.get(run_id, 0) >= self._per_run:
            raise LlmRequestError(
                "协作模型调用额度已用尽", code="collaboration_call_budget",
                public_code="BUDGET_EXCEEDED",
            )
        self._calls[run_id] = self._calls.get(run_id, 0) + 1
        self._total += 1

    async def stream(self, adapter: LlmAdapter, run_id: str, request: LlmRequest) -> AsyncIterator[StreamChunk]:
        """只在真正派发模型流时占用并发，等待工具、专家或人工不占模型槽位。"""
        async with self._capacity:
            self._admit(run_id)
            self._active += 1
            try:
                stream = adapter.stream(request)
                try:
                    async for chunk in stream:
                        yield chunk
                finally:
                    close = getattr(stream, "aclose", None)
                    if close is not None:
                        await close()
            finally:
                self._active -= 1


@dataclass(frozen=True)
class BudgetedAdapter:
    """包装既有协议适配器，重试仍由唯一 AgentLoop 管理。"""

    adapter: LlmAdapter
    budget: ModelCallBudget
    run_id: str

    def __post_init__(self) -> None:
        """调用归属由服务端构造，空身份拒绝参与共享账本。"""
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("模型调用必须指定 run_id")

    def stream(self, request: LlmRequest) -> AsyncIterator[StreamChunk]:
        """透传原始请求与供应商片段，不改变模型用途或工具视野。"""
        return self.budget.stream(self.adapter, self.run_id, request)
