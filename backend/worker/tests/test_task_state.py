"""Worker 终态锁定回归测试。"""

from app.models import Task
from app.task_state import claim_running_task_for_terminal_write


class _Query:
    """记录行锁调用的最小 SQLAlchemy 查询桩。"""

    def __init__(self, task: Task | None):
        self.task = task
        self.locked = False

    def filter(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def first(self):
        return self.task


class _Db:
    """观测刷新与行锁的最小数据库桩。"""

    def __init__(self, task: Task | None):
        self.query_result = _Query(task)
        self.expired = False

    def expire_all(self):
        self.expired = True

    def query(self, *_args, **_kwargs):
        return self.query_result


def _task(status: str) -> Task:
    """构造不落库的 Worker 任务。"""
    return Task(id="t-finish", kind="benchmark", status=status, config={}, progress={}, result={})


def test_claim_running_task_locks_and_returns_running_task():
    """完成路径只能在锁定后继续写 running 任务。"""
    task = _task("running")
    db = _Db(task)

    assert claim_running_task_for_terminal_write(db, task.id) is task
    assert db.expired is True
    assert db.query_result.locked is True


def test_claim_running_task_rejects_existing_terminal_task():
    """API 已提交取消或失败时，Worker 的陈旧对象不得再覆盖终态。"""
    task = _task("cancelled")
    db = _Db(task)

    assert claim_running_task_for_terminal_write(db, task.id) is None
    assert db.expired is True
    assert db.query_result.locked is True
