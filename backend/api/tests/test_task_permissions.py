"""任务取消与读取权限负例单测（M1 出口：仅创建者可取消自己的任务）。

通过轻量 FakeDb 桩替换 SQLAlchemy 会话，验证 _owned_task 的三分支
（不存在 / 非创建者 / 创建者）与 cancel 的终态拒绝；不依赖数据库。
"""

import pytest

from app.errors import AppError, ErrorCode
from app.models import Task, User
from app.routers.tasks import cancel_task


class _FakeQuery:
    """吞掉任意 filter 链并返回预置结果的最小查询桩。"""

    def __init__(self, result):
        self._result = result
        self.locked = False

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result

    def with_for_update(self):
        self.locked = True
        return self


class _FakeDb:
    """覆盖本测试所需 query/add/commit/refresh 的最小会话桩。"""

    def __init__(self, result=None):
        self._query = _FakeQuery(result)
        self.added: list = []
        self.commit_calls = 0

    def query(self, *args, **kwargs):
        return self._query

    def add(self, obj, *args, **kwargs):
        self.added.append(obj)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        pass

    def refresh(self, *args, **kwargs):
        pass


class _FakeRequest:
    """仅提供 client 属性探测的最小请求桩。"""

    client = None


def _task(status: str, creator: str = "user-owner") -> Task:
    """构造不落库的任务 ORM 实例。"""
    return Task(
        id="t-1",
        kind="benchmark",
        status=status,
        created_by=creator,
        config={},
        progress={},
        result={},
    )


def test_owned_task_missing_raises_not_found():
    # 任务不存在：统一 NOT_FOUND
    with pytest.raises(AppError) as exc:
        from app.routers.tasks import _owned_task

        _owned_task(_FakeDb(result=None), "t-404", "user-1")
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_owned_task_non_creator_denied():
    # 非创建者：资源存在但无权操作，返回 UNAUTHORIZED（M1 出口负例）
    from app.routers.tasks import _owned_task

    task = _task("queued", creator="user-owner")
    with pytest.raises(AppError) as exc:
        _owned_task(_FakeDb(result=task), "t-1", "user-other")
    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_owned_task_creator_allowed():
    # 创建者本人：正常返回任务对象
    from app.routers.tasks import _owned_task

    task = _task("queued", creator="user-1")
    assert _owned_task(_FakeDb(result=task), "t-1", "user-1") is task


def test_cancel_terminal_task_rejected():
    # 终态任务不可取消：VALIDATION 拒绝且不产生任何写操作
    user = User(id="user-owner", username="owner")
    db = _FakeDb(result=_task("succeeded", creator="user-owner"))
    with pytest.raises(AppError) as exc:
        cancel_task(task_id="t-1", request=_FakeRequest(), db=db, user=user)

    assert exc.value.code == ErrorCode.VALIDATION
    assert db.added == []


def test_cancel_by_non_creator_is_unauthorized_without_side_effects():
    """路由入口必须先鉴权，非创建者不能留下半条取消写入。"""
    user = User(id="user-other", username="other")
    task = _task("running", creator="user-owner")
    db = _FakeDb(result=task)

    with pytest.raises(AppError) as exc:
        cancel_task(task_id="t-1", request=_FakeRequest(), db=db, user=user)

    assert exc.value.code == ErrorCode.UNAUTHORIZED
    assert task.status == "running"
    assert task.cancel_requested_at is None
    assert task.finished_at is None
    assert db.added == []
    assert db.commit_calls == 0
    assert db._query.locked is True


def test_cancel_by_creator_marks_cancelled_with_audit():
    # 创建者取消 queued 任务：状态翻转为 cancelled 并写入审计
    user = User(id="user-owner", username="owner")
    task = _task("queued", creator="user-owner")
    db = _FakeDb(result=task)

    out = cancel_task(task_id="t-1", request=_FakeRequest(), db=db, user=user)

    assert out["status"] == "cancelled"
    assert task.cancel_requested_at is not None
    assert task.finished_at == task.cancel_requested_at
    # 事件时间线与审计日志均被追加
    kinds = {type(obj).__name__ for obj in db.added}
    assert {"TaskEvent", "AuditLog"} <= kinds
    audit = next(obj for obj in db.added if type(obj).__name__ == "AuditLog")
    assert audit.action == "task_cancel"
