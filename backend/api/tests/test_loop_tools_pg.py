"""独立 PostgreSQL 上验证工具事实与 guard 原子提交，不读取业务库配置。"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.harness.execution.loop_tools import ToolExecutionResult
from app.harness.execution.scheduler import ToolScheduler
from app.harness.memory.agent_events import SessionLog
from app.models import (
    AgentEvent,
    AgentRuntimeState,
    Base,
    Message,
    Session,
    SessionStream,
    User,
    Workspace,
    WorkspaceExecutionGuard,
)
from tests.test_loop_tools import bridge_for, call, settings


@pytest.fixture
def pg_logs():
    """测试库内创建随机独立 schema，仅清理本例自建 schema。"""
    url = os.getenv("LOOP_TOOLS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要显式 LOOP_TOOLS_TEST_DATABASE_URL")
    schema = "loop_tools_" + uuid4().hex
    # PG advisory lock 在整个数据库共享，会话也使用独立 UUID，避免并行测试互斥。
    session_ids = (str(uuid4()), str(uuid4()))
    control = create_engine(url)
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    factory, logs = sessionmaker(engine), []
    try:
        Base.metadata.create_all(engine, tables=[m.__table__ for m in (
            User, Workspace, Session, Message, AgentRuntimeState, AgentEvent,
            SessionStream, WorkspaceExecutionGuard,
        )])
        with factory.begin() as db:
            db.add(User(id="test-user", username="loop-tools", password_hash="not-a-login"))
            db.flush()
            db.add_all([Session(id=sid, user_id="test-user", engine_version="agent_loop_v2") for sid in session_ids])
        for sid in session_ids:
            log = SessionLog(sid, factory, actor_id="test-user")
            log.claim()
            logs.append(log)
        yield logs, factory
    finally:
        for log in logs:
            log.close()
        engine.dispose()
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


async def execute(log, bridge, calls):
    """调度器使用正式 SessionLog。"""
    return await ToolScheduler(settings(), bridge.available_tools()).execute(
        session_id=log.session_id, log=log, turn=1, step=1, attempt_id="attempt-a",
        calls=calls, emit=lambda e: None, allow_dispatch=True,
    )


@pytest.mark.asyncio
async def test_pg_real_results_release_with_commit(pg_logs, tmp_path):
    """文件结果与 guard 释放由正式 Store 在同一事务提交。"""
    logs, factory = pg_logs
    messages = await execute(logs[0], bridge_for(tmp_path), [call("write", "w", file_path="x", content="full body"), call("read", "r", file_path="x")])
    assert "full body" in messages[-1]["content"]
    with factory() as db:
        guards = list(db.scalars(select(WorkspaceExecutionGuard)))
        assert len(guards) == 2 and all(g.status == "released" for g in guards)
        assert len(list(db.scalars(select(AgentEvent).where(AgentEvent.type == "tool/result")))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["description", "prompt", "goal"])
async def test_pg_task_plan_commits_complete_snapshot_and_failed_draft_does_not_replace(pg_logs, tmp_path, field):
    """task 成功才原子写会话快照；失败参数只留下工具终态，不污染当前计划。"""
    logs, factory = pg_logs
    logs[0].append("turn/start", {"turn": 1})
    bridge = bridge_for(tmp_path, names=("task",))
    goal = "检查任务规划链路中的旧参数兼容、工具结果持久化以及会话断线后的完整回放"
    initial = {
        field: goal,
        "steps": [
            {"title": "写入完整计划", "status": "completed"},
            {"title": "验证会话回放", "status": "in_progress"},
        ],
    }
    await execute(logs[0], bridge, [call("task", "task-ok", **initial)])

    failed = {
        "description": "不应覆盖的草稿",
        "steps": [
            {"title": "重复步骤", "status": "pending"},
            {"title": "重复步骤", "status": "in_progress"},
        ],
    }
    await execute(logs[0], bridge, [call("task", "task-failed", **failed)])

    events = logs[0].read()
    snapshots = [event for event in events if event["type"] == "task_plan/updated"]
    assert len(snapshots) == 1
    assert snapshots[0]["data"]["plan"]["goal"] == (goal if field == "description" else goal[:24] + "…")
    assert snapshots[0]["data"]["plan"]["steps"] == initial["steps"]
    assert snapshots[0]["data"]["plan"]["counts"] == {"pending": 0, "in_progress": 1, "completed": 1}
    assert any(event["type"] == "tool/result" and event["data"]["call_id"] == "task-failed" and event["data"]["status"] != "succeeded" for event in events)
    with factory() as db:
        streams = list(db.scalars(select(SessionStream).where(SessionStream.session_id == logs[0].session_id)))
        assert [stream.projection_kind for stream in streams].count("task_plan.updated") == 1


@pytest.mark.asyncio
async def test_pg_unknown_quarantines_cross_session_and_reopen(pg_logs, tmp_path):
    """未知结果跨会话和重新打开日志仍隔离，同 scope 读取也被阻止。"""
    logs, factory = pg_logs

    async def runner(*args):
        """模拟已派发但没有终止证据的远端执行。"""
        return ToolExecutionResult("unreachable", "outcome_unknown", "runner_outcome_unknown")

    bridge = bridge_for(tmp_path, names=("bash",), runner=runner, runner_instance_id=str(uuid4()))
    await execute(logs[0], bridge, [call("bash", command="echo controlled")])
    logs[0].close()
    logs[0] = SessionLog(logs[0].session_id, factory, actor_id="test-user")
    logs[0].claim()
    (tmp_path / "x").write_text("do not read")
    messages = await execute(logs[1], bridge_for(tmp_path, names=("read",)), [call("read", file_path="x")])
    assert messages[0]["is_error"] and "do not read" not in messages[0]["content"]
    with factory() as db:
        guards = list(db.scalars(select(WorkspaceExecutionGuard)))
        assert len(guards) == 1 and guards[0].status == "quarantined"
        assert not list(db.scalars(select(AgentEvent).where(AgentEvent.session_id == logs[1].session_id, AgentEvent.type == "tool/dispatch")))


@pytest.mark.asyncio
async def test_pg_failed_result_commit_keeps_guard(pg_logs, tmp_path, monkeypatch):
    """实际写入成功但结果提交失败，guard 不得提前释放。"""
    logs, factory = pg_logs
    original = logs[0].append

    def append(kind, data):
        """模拟结果事务开始前数据库不可用。"""
        if kind == "tool/result":
            raise OSError("test result store failure")
        return original(kind, data)

    monkeypatch.setattr(logs[0], "append", append)
    with pytest.raises(OSError):
        await execute(logs[0], bridge_for(tmp_path), [call("write", file_path="x", content="written")])
    assert (tmp_path / "x").read_text() == "written"
    with factory() as db:
        guards = list(db.scalars(select(WorkspaceExecutionGuard)))
        assert len(guards) == 1 and guards[0].status == "active"
        assert not list(db.scalars(select(AgentEvent).where(AgentEvent.type == "tool/result")))
