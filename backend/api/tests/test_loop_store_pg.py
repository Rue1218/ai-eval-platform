"""真实隔离 PG 的事实/游标/写者/Worker 桥测试。

运行前显式设置 LOOP_TEST_DATABASE_URL；不建表、不迁移、不清空共享数据库。
每例只删除自身 UUID 用户和会话关联行。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import sessionmaker

from app.errors import AppError, ErrorCode
from app.harness.memory.agent_events import SessionLog, canonical_scope
from app.models import (
    AgentEvent,
    AgentRuntimeState,
    Message,
    Session,
    SessionStream,
    Task,
    TaskEvent,
    User,
    WorkspaceExecutionGuard,
    WsEvent,
)


@dataclass
class PgCase:
    """每例独立身份与会话集合，清理严格限制在本例创建的 UUID。"""

    factory: sessionmaker
    user_id: str
    observer_id: str
    session_ids: list[str] = field(default_factory=list)

    def session(self, *, team=False) -> str:
        """创建真实平台会话，不创建第二套简化 schema。"""
        identity = str(uuid4())
        with self.factory.begin() as db:
            db.add(Session(id=identity, user_id=self.user_id,
                           title="Loop PG integration", engine_version="agent_loop_v2",
                           visibility="team" if team else "private"))
        self.session_ids.append(identity)
        return identity

    @contextmanager
    def log(self, session_id=None):
        """显式取得并始终释放 PG writer 连接。"""
        value = SessionLog(session_id or self.session(), self.factory, actor_id=self.user_id)
        value.claim()
        try:
            yield value
        finally:
            value.close()


@pytest.fixture
def pg_case():
    """只连显式测试 URL；缺配置 skip，已配置但 schema/连接错误直接失败。"""
    url = os.environ.get("LOOP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 LOOP_TEST_DATABASE_URL 指向已迁移的隔离 PostgreSQL")
    engine = create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    assert engine.dialect.name == "postgresql"
    with engine.connect() as connection:
        assert connection.execute(text("select to_regclass('agent_events')")).scalar()
        assert connection.execute(text("select to_regclass('session_stream')")).scalar()
    owner, observer = str(uuid4()), str(uuid4())
    case = PgCase(factory, owner, observer)
    with factory.begin() as db:
        db.add_all([
            User(id=owner, username=f"loop-{owner}", password_hash="test-only-not-login",
                 must_change_password=False),
            User(id=observer, username=f"loop-{observer}", password_hash="test-only-not-login",
                 must_change_password=False),
        ])
    try:
        yield case
    finally:
        # 只清理本例创建的精确外键域，绝不 TRUNCATE、drop_all 或删除共享数据。
        with factory.begin() as db:
            task_ids = select(Task.id).where(Task.session_id.in_(case.session_ids))
            db.execute(delete(TaskEvent).where(TaskEvent.task_id.in_(task_ids)))
            for model in (
                WorkspaceExecutionGuard, SessionStream, AgentEvent, AgentRuntimeState,
                Message, WsEvent, Task,
            ):
                db.execute(delete(model).where(model.session_id.in_(case.session_ids)))
            db.execute(delete(Session).where(Session.id.in_(case.session_ids)))
            db.execute(delete(User).where(User.id.in_([owner, observer])))
        engine.dispose()


def dispatch(log, scope, *, call_id=None, access="write"):
    """写真实 dispatch 事实并由 Store 同事务取得 scope guard。"""
    call = call_id or str(uuid4())
    event = log.append("tool/dispatch", {
        "turn": 1, "step": 1, "attempt_id": f"a-{call}", "call_id": call,
        "execution_id": str(uuid4()), "name": "read" if access == "read" else "edit",
        "scope_path": canonical_scope(str(scope)), "access": access,
    })
    return event["data"]


def result(log, dispatched, status):
    """写工具终态，依赖真实 Store 结算 guard。"""
    return log.append("tool/result", {
        **dispatched, "content": "actual tool receipt", "status": status,
    })


def test_pg_rolls_back_fact_message_and_cursor_together(pg_case):
    """事务异常必须回滚事实、消息读模型与 cursor，后继提交不能留下空洞。"""
    with pg_case.log() as log:
        with pytest.raises(RuntimeError, match="abort transaction"):
            with log._transaction() as (db, session, state):
                log._append(db, session, state, "turn/start", {"turn": 1})
                log._append(db, session, state, "user/message", {"turn": 1, "content": "rolled back"})
                raise RuntimeError("abort transaction")
        assert log.read() == [] and log.high_water() == 0
        with pg_case.factory() as db:
            assert db.scalar(select(func.count()).select_from(Message).where(
                Message.session_id == log.session_id,
            )) == 0
            state = db.get(AgentRuntimeState, log.session_id)
            assert state.next_seq == 0 and state.active_turn is None
        event = log.append("turn/start", {"turn": 1})
        assert event["seq"] == 0
        assert [frame["cursor"] for frame in log.stream()] == [1]


def test_pg_multi_projection_is_atomic_and_idempotent(pg_case):
    """一次 assistant 事实生成两帧，同 logical key 重试不得增加 seq/cursor。"""
    with pg_case.log() as log:
        data = {"turn": 1, "step": 1, "attempt_id": "a", "content": "completed",
                "message": {"role": "assistant", "content": "completed"},
                "protocol_state": {"opaque": "PRIVATE"}, "tool_calls": []}
        first = log.append("assistant/message", data)
        again = log.append("assistant/message", data)
        assert first == again and first["seq"] == 0
        assert [f["type"] for f in log.stream()] == ["assistant.message", "assistant.end"]
        assert [f["cursor"] for f in log.stream()] == [1, 2]
        assert all(f["correlation"]["source_seq"] == 0 for f in log.stream())
        assert all("protocol_state" not in f["data"] for f in log.stream())
        with pytest.raises(AppError):
            log.append("assistant/message", {**data, "content": "conflicting"})
        assert log.high_water() == 2 and len(log.read()) == 1


def test_pg_two_logs_exclude_writers_but_allow_readers(pg_case):
    """PG 专用连接持锁排他，读取无需 claim；释放后第二日志才能写。"""
    sid = pg_case.session()
    first = SessionLog(sid, pg_case.factory, actor_id=pg_case.user_id)
    second = SessionLog(sid, pg_case.factory, actor_id=pg_case.user_id)
    try:
        first.claim()
        first.append("turn/start", {"turn": 1})
        with pytest.raises(AppError) as error:
            second.claim()
        assert error.value.code == ErrorCode.CONCURRENCY
        assert second.read()[0]["seq"] == 0 and second.high_water() == 1
        with pytest.raises(AppError):
            second.append("turn/end", {"turn": 1, "reason": "completed"})
        first.close()
        second.claim()
        second.append("turn/end", {"turn": 1, "reason": "interrupted"})
        assert [e["seq"] for e in second.read()] == [0, 1]
    finally:
        first.close()
        second.close()


def test_pg_worker_bridge_only_projects_business_and_deduplicates(pg_case):
    """真实 outbox 转 v2；旧 Agent 帧不串入，Worker 终态不结束 Agent turn。"""
    with pg_case.log() as log:
        task_id = str(uuid4())
        with pg_case.factory.begin() as db:
            db.add(Task(id=task_id, session_id=log.session_id, created_by=pg_case.user_id,
                        kind="benchmark", status="succeeded"))
            db.add_all([
                WsEvent(session_id=log.session_id, event_id=1, task_id=None,
                        event="assistant_delta", payload={"delta": "legacy"}),
                WsEvent(session_id=log.session_id, event_id=2, task_id=task_id,
                        event="progress", payload={"progress": {"done": 1}}),
                WsEvent(session_id=log.session_id, event_id=3, task_id=task_id,
                        event="report", payload={"report_id": "report-ref"}),
                WsEvent(session_id=log.session_id, event_id=4, task_id=task_id,
                        event="task_state", payload={"status": "succeeded"}),
            ])
        log.bridge_worker()
        frames = log.stream()
        assert [f["type"] for f in frames] == ["task.progress", "task.report", "task.end"]
        assert [f["cursor"] for f in frames] == [1, 2, 3]
        assert all(f["correlation"] == {"task_id": task_id} for f in frames)
        assert log.read() == []
        log.bridge_worker()
        assert log.stream() == frames


def test_pg_scope_quarantine_survives_restart_and_blocks_other_session(pg_case, tmp_path):
    """未知执行跨日志重建仍隔离祖先/子目录，可信对账后才可重新派发。"""
    (tmp_path / "nested").mkdir()
    sid = pg_case.session()
    with pg_case.log(sid) as first:
        started = dispatch(first, tmp_path)
        result(first, started, "outcome_unknown")
    with pg_case.log() as second:
        before = second.high_water()
        with pytest.raises(AppError) as error:
            dispatch(second, tmp_path / "nested", access="read")
        assert error.value.code == ErrorCode.CONCURRENCY
        assert second.high_water() == before and second.read() == []
        with pg_case.log(sid) as restarted:
            with pytest.raises(AppError):
                restarted.reconcile_execution(started["execution_id"], {"status": "failed"})
            restarted.reconcile_execution(started["execution_id"], {
                "execution_id": started["execution_id"],
                "status": "failed", "process_tree_terminated": True,
                "termination_evidence": "process_exited",
            })
        next_call = dispatch(second, tmp_path / "nested")
        result(second, next_call, "succeeded")
        with pg_case.factory() as db:
            assert db.get(WorkspaceExecutionGuard, started["execution_id"]).status == "released"


def test_pg_parallel_reads_share_scope_but_writer_waits(pg_case, tmp_path):
    """两个会话只读 guard 可共存，冲突写入拒绝且拒绝事务不消耗序号。"""
    with pg_case.log() as first, pg_case.log() as second, pg_case.log() as third:
        read1 = dispatch(first, tmp_path, access="read")
        read2 = dispatch(second, tmp_path, access="read")
        with pytest.raises(AppError):
            dispatch(third, tmp_path)
        assert third.read() == [] and third.high_water() == 0
        result(first, read1, "succeeded")
        with pytest.raises(AppError):
            dispatch(third, tmp_path)
        result(second, read2, "succeeded")
        write = dispatch(third, tmp_path)
        result(third, write, "succeeded")
        assert [e["seq"] for e in third.read()] == [0, 1]
