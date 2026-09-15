"""前台协作的回合所有权：主回合写终态前，必须收拢全部子任务。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


class TurnChildren:
    """仅管理当前进程的子任务生命周期，不承担持久调度、状态恢复或授权。"""

    def __init__(self, *, max_children: int = 8):
        """限额按累计创建数计算，结束子任务不会自动返还实例额度。"""
        if type(max_children) is not int or max_children < 1:
            raise ValueError("子任务累计上限必须是正整数")
        self._limit = max_children
        self._tasks: list[asyncio.Task[Any]] = []
        self._closing: asyncio.Task[None] | None = None

    def start(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> asyncio.Task[Any]:
        """先检查归属和额度，再创建协程，避免拒绝时留下未等待的协程。"""
        if self._closing is not None:
            raise RuntimeError("主回合已进入收尾，不能创建子任务")
        if len(self._tasks) >= self._limit:
            raise RuntimeError("子任务累计上限已用尽")
        task = asyncio.create_task(factory(), name=f"agent-child-{len(self._tasks) + 1}")
        self._tasks.append(task)
        # 及时取走异常，结果仍保留在原 Task 中供协调者查询。
        task.add_done_callback(self._observe)
        return task

    @staticmethod
    def _observe(task: asyncio.Task[Any]) -> None:
        """消费后台异常告警，不将失败误判成协作成功。"""
        if not task.cancelled():
            task.exception()

    async def _drain(self) -> None:
        """先向所有子任务发取消，再等待各自 finally 完成，避免串行停机。"""
        for task in self._tasks:
            # 单独停止的专家可能仍在 finally 中等待资源释放；重复 cancel 会把
            # 此处的 await 再次打断。已有取消请求时只等待，不能以 task 未结束为由重发。
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def close(self, *, propagate_cancel: bool = True) -> None:
        """幂等收拢；重复取消不能打断清理，取消信号在清理结束后重新传播。"""
        if self._closing is None:
            self._closing = asyncio.create_task(self._drain(), name="agent-children-drain")
        interrupted = False
        while not self._closing.done():
            try:
                await asyncio.shield(self._closing)
            except asyncio.CancelledError:
                interrupted = True
        self._closing.result()
        if interrupted and propagate_cancel:
            raise asyncio.CancelledError
