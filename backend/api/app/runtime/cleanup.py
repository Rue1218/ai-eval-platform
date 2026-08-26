"""运行时基础设施：检查点 TTL 后台清理（M9-D6）。

调度载体定为 **API 进程 lifespan 周期任务**，不新增 Worker 职责：
默认 ``memory`` 引擎的检查点只存在于 API 进程；``postgres`` 引擎同库
亦可由本循环清理。多副本时删除幂等。
"""

from __future__ import annotations

import asyncio

from app.agent.log import agent_trace
from app.harness.memory import cleanup_orphaned_checkpoints, get_default_checkpointer

# M9 §3.3：默认每 6 小时跑一轮 TTL
DEFAULT_CLEANUP_INTERVAL_SECONDS = 6 * 3600


async def checkpoint_ttl_loop(
    *,
    interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS,
) -> None:
    """周期执行孤儿检查点 TTL 清理，直到任务被取消。"""
    while True:
        try:
            removed = await asyncio.to_thread(
                cleanup_orphaned_checkpoints, get_default_checkpointer()
            )
            if removed:
                agent_trace(f"checkpoint ttl cleanup removed={removed}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            agent_trace(f"checkpoint ttl cleanup failed type={type(exc).__name__}")
        await asyncio.sleep(interval_seconds)
