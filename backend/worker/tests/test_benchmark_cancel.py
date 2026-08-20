"""Benchmark 最终汇总不覆盖取消终态的回归测试。"""

from types import SimpleNamespace

from app import benchmark
from app.models import Task


class _NoWriteDb:
    """取消已生效时，_finish 不应触发任何写入。"""

    def __init__(self):
        self.added: list = []
        self.commit_calls = 0

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commit_calls += 1


def _task(status: str) -> Task:
    """构造与数据库最终状态分离的任务对象，模拟 Worker 陈旧缓存。"""
    return Task(
        id="t-race",
        kind="benchmark",
        status=status,
        config={"profile_ids": []},
        progress={},
        result={},
    )


def test_finish_does_not_overwrite_cancelled_task_from_stale_worker(monkeypatch):
    """最后一批完成后若数据库已取消，不建报告、不推完成事件。"""
    stale_task = _task("running")
    canonical_task = _task("cancelled")
    db = _NoWriteDb()
    pushes: list[tuple] = []

    monkeypatch.setattr(
        benchmark,
        "claim_running_task_for_terminal_write",
        lambda _db, _task_id: None if canonical_task.status == "cancelled" else canonical_task,
    )
    monkeypatch.setattr(benchmark, "push_ws", lambda *args, **kwargs: pushes.append((args, kwargs)))

    completed = benchmark._finish(
        db,
        stale_task,
        SimpleNamespace(id="d-1", name="dataset", version=1),
        "contain",
        1,
    )

    assert completed is False
    assert canonical_task.status == "cancelled"
    assert db.added == []
    assert db.commit_calls == 0
    assert pushes == []
