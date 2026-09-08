"""回滚到旧引擎仍遵守持久隔离，真实 PostgreSQL 与本地写入验证。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.errors import AppError, ErrorCode
from app.harness.execution.context import ToolExecutionContext
from app.harness.execution.workspace_guard import configure, guarded_call
from app.models import Session, WorkspaceExecutionGuard

pytest_plugins = ["tests.test_loop_tools_pg"]


def test_legacy_cannot_write_quarantined_new_scope(pg_logs, tmp_path):
    """即使旧会话不运行新循环，也不能写入已隔离的重叠子目录。"""
    logs, factory = pg_logs
    new_log = logs[0]
    legacy = str(uuid4())
    with factory.begin() as db:
        db.add(Session(id=legacy, user_id=new_log.actor_id, engine_version="legacy"))
    execution_id = str(uuid4())
    identity = {"turn": 1, "step": 1, "attempt_id": "legacy-guard-test", "call_id": "remote-call"}
    new_log.append("tool/dispatch", {**identity, "execution_id": execution_id,
                                    "scope_path": str(tmp_path), "access": "write"})
    new_log.append("tool/result", {**identity, "status": "outcome_unknown", "content": "unknown"})
    target = tmp_path / "should-not-exist.txt"
    context = ToolExecutionContext(session_id=legacy, user_id=new_log.actor_id, sandbox_dir=str(tmp_path))
    definition = SimpleNamespace(name="write", permission_policy=SimpleNamespace(workspace="write"))
    configure(factory)
    try:
        with pytest.raises(AppError) as caught:
            guarded_call(definition, context, lambda: target.write_text("unexpected"))
        assert caught.value.code == ErrorCode.CONCURRENCY
        assert not target.exists()
    finally:
        configure(None)


def test_legacy_unconfirmed_bash_result_remains_quarantined(pg_logs, tmp_path):
    """旧 Runner 的错误结果无法提供停止证据，工作区必须继续隔离。"""
    logs, factory = pg_logs
    session_id = str(uuid4())
    with factory.begin() as db:
        db.add(Session(id=session_id, user_id=logs[0].actor_id, engine_version="legacy"))
    context = ToolExecutionContext(session_id=session_id, user_id=logs[0].actor_id,
                                   sandbox_dir=str(tmp_path), call_id="legacy-call")
    definition = SimpleNamespace(name="bash", permission_policy=SimpleNamespace(workspace="write"))
    result = SimpleNamespace(ok=False)
    configure(factory)
    try:
        assert guarded_call(definition, context, lambda: result) is result
    finally:
        configure(None)
    with factory() as db:
        guard = db.execute(select(WorkspaceExecutionGuard).where(WorkspaceExecutionGuard.session_id == session_id)).scalar_one()
        assert guard.status == "quarantined"
        assert guard.evidence["thread_finished"] is True
