"""业务确认前后的共享准备服务：事务归属、冻结版本和资源权限。"""

import pytest

from app.errors import AppError, ErrorCode
from app.harness.execution.task_tools import create_task_safe, prepare_task_request
from app.models import AuditLog, Dataset, DatasetVersion, ProtocolProfile, Task
from tests.test_task_tools import _benchmark_args, _ctx, _FakeDb, _Query, _SessionRow


def test_prepare_does_not_commit_close_or_consume_card():
    """确认卡存在时可准备 spec，helper 不入队、不清卡。"""
    row = _SessionRow(pending_confirm={"id": "current-card"})
    db = _FakeDb(session_row=row, task_query=[])
    kind, spec, parent = prepare_task_request(db, _benchmark_args(), _ctx())
    assert kind == "benchmark" and spec["dataset_id"] == "d1" and parent is None
    assert db.commit_calls == 0 and not db.closed and not db.added
    assert row.pending_confirm == {"id": "current-card"}


@pytest.mark.parametrize("owner", ["someone-else", None])
def test_prepare_rejects_foreign_parent(owner):
    """父任务成功也不能绕过创建者权限。"""
    parent = Task(id="parent", kind="benchmark", status="succeeded", created_by=owner)
    db = _FakeDb(session_row=_SessionRow(), task_query=[], tasks={"parent": parent})
    with pytest.raises(AppError) as error:
        prepare_task_request(db, {"kind": "stress", "parent_task_id": "parent"}, _ctx())
    assert error.value.code == ErrorCode.UNAUTHORIZED
    assert db.commit_calls == 0 and not db.closed


def test_prepare_rejects_missing_profile():
    """共享协议档目录中不存在的评测档仍必须被拒绝。"""
    db = _FakeDb(session_row=_SessionRow(), task_query=[], profiles={})
    with pytest.raises(AppError) as error:
        prepare_task_request(db, _benchmark_args(), _ctx())
    assert error.value.code == ErrorCode.NOT_FOUND and db.commit_calls == 0


def test_prepare_accepts_shared_profile_created_by_another_member():
    """全员同权时，创建者只保留审计用途，不限制共享协议档参与评测。"""
    db = _FakeDb(session_row=_SessionRow(), task_query=[], profiles={
        "p1": ProtocolProfile(id="p1", created_by="other"),
    })
    kind, spec, parent = prepare_task_request(db, _benchmark_args(), _ctx())
    assert kind == "benchmark" and spec["profile_ids"] == ["p1"] and parent is None
    assert db.commit_calls == 0


def test_prepare_accepts_shared_judge_profile():
    """裁判档与评测档遵循同一共享目录权限口径。"""
    db = _FakeDb(session_row=_SessionRow(), task_query=[], profiles={
        "p1": ProtocolProfile(id="p1", created_by="u1"),
        "judge": ProtocolProfile(id="judge", created_by="other"),
    })
    kind, spec, _ = prepare_task_request(
        db,
        _benchmark_args(run={"sample_size": 1, "use_judge": True, "judge_profile_id": "judge"}),
        _ctx(),
    )
    assert kind == "benchmark" and spec["run"]["judge_profile_id"] == "judge"


def test_prepare_checks_missing_profile():
    """已删除的裁判档必须按不存在处理。"""
    db = _FakeDb(session_row=_SessionRow(), task_query=[], profiles={
        "p1": ProtocolProfile(id="p1", created_by="u1"),
    })
    with pytest.raises(AppError) as error:
        prepare_task_request(
            db,
            _benchmark_args(run={"sample_size": 1, "use_judge": True, "judge_profile_id": "judge"}),
            _ctx(),
        )
    assert error.value.code == ErrorCode.NOT_FOUND


def test_prepare_freezes_version():
    """准备结果携带发布版本而非可变 staging。"""
    dataset = Dataset(id="d1", name="published", active_version_id="v1")
    version = DatasetVersion(id="v1", dataset_id="d1", version_no=3)
    db = _FakeDb(session_row=_SessionRow(), task_query=[], datasets={"d1": dataset})
    original = db.query
    db.query = lambda model: _Query(version) if model is DatasetVersion else original(model)
    _, spec, _ = prepare_task_request(db, _benchmark_args(), _ctx())
    assert spec["dataset_version_id"] == "v1" and spec["dataset_version_no"] == 3
    assert db.commit_calls == 0 and not db.closed


def test_quota_audit_commit_belongs_to_caller(monkeypatch):
    """helper 暂存拒绝审计，旧入口保留独立提交审计的行为。"""
    monkeypatch.setattr("app.harness.execution.worker_bridge.count_active_tasks", lambda *args, **kwargs: 999999)
    db = _FakeDb(session_row=_SessionRow(), task_query=[])
    with pytest.raises(AppError):
        prepare_task_request(db, _benchmark_args(), _ctx())
    assert db.commit_calls == 0 and not db.closed
    assert any(isinstance(row, AuditLog) and row.action == "task_quota_rejected" for row in db.added)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError):
        create_task_safe(_benchmark_args(), _ctx())
    assert db.commit_calls == 1 and db.closed
