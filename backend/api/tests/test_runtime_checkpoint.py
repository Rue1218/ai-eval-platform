"""M9 运行时：检查点 TTL 后台任务（不依赖 DB）。"""

import asyncio

import pytest

from app.runtime.cleanup import checkpoint_ttl_loop


@pytest.mark.asyncio
async def test_checkpoint_ttl_loop_runs_and_cancels(monkeypatch) -> None:
    """R-A3：后台循环至少执行一次 TTL 清理，取消后退出。"""
    calls = {"n": 0}

    def fake_cleanup(_checkpointer: object) -> int:
        calls["n"] += 1
        return 1

    monkeypatch.setattr("app.runtime.cleanup.cleanup_orphaned_checkpoints", fake_cleanup)
    monkeypatch.setattr(
        "app.runtime.cleanup.get_default_checkpointer", lambda: object()
    )
    task = asyncio.create_task(checkpoint_ttl_loop(interval_seconds=0.01))
    for _ in range(50):
        if calls["n"] >= 1:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["n"] >= 1
