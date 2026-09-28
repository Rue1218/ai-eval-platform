"""业务确认前后的用例任务准备与事务归属。"""

import pytest

from app.errors import AppError, ErrorCode
from app.harness.execution.task_tools import create_task_safe, prepare_task_request
from app.models import AuditLog
from tests.test_task_tools import _benchmark_args, _ctx, _FakeDb, _SessionRow, _testcase_args


def test_prepare_does_not_commit_close_or_consume_card():
    """确认卡存在时可准备用例规格，helper 不入队、不清卡。"""
    row = _SessionRow(pending_confirm={"id": "current-card"})
    db = _FakeDb(session_row=row, task_query=[])
    kind, spec, parent = prepare_task_request(db, _testcase_args(), _ctx())
    assert kind == "testcase" and spec["case_source"] == {"text": "登录需求"} and parent is None
    assert db.commit_calls == 0 and not db.closed and not db.added
    assert row.pending_confirm == {"id": "current-card"}


def test_prepare_rejects_retired_kind_before_resource_access():
    """旧评测请求在查询数据集和配额前被业务门禁拒绝。"""
    db = _FakeDb(session_row=_SessionRow(), task_query=[])
    with pytest.raises(AppError) as error:
        prepare_task_request(db, _benchmark_args(), _ctx())
    assert error.value.code == ErrorCode.VALIDATION
    assert db.commit_calls == 0 and not db.closed and not db.added


def test_quota_audit_commit_belongs_to_caller(monkeypatch):
    """用例任务配额拒绝仍由调用方提交审计。"""
    monkeypatch.setattr("app.harness.execution.worker_bridge.count_active_tasks", lambda *args, **kwargs: 999999)
    db = _FakeDb(session_row=_SessionRow(), task_query=[])
    with pytest.raises(AppError):
        prepare_task_request(db, _testcase_args(), _ctx())
    assert db.commit_calls == 0 and not db.closed
    assert any(isinstance(row, AuditLog) and row.action == "task_quota_rejected" for row in db.added)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError):
        create_task_safe(_testcase_args(), _ctx())
    assert db.commit_calls == 1 and db.closed
