"""P1 专家协作：真实持久实体、并行归属、幂等与独立事实日志。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.collaboration import CollaborationCoordinator
from app.agent.collaboration_scope import TurnChildren
from app.agent.model_budget import ModelCallBudget
from app.agent.subagent_log import SubagentLog
from app.agent.subagent_tools import register_subagent_tools
from app.errors import AppError
from app.harness.execution.registry import build_default_registry
from app.models import (
    AgentCollaboration,
    AgentCommandReceipt,
    AgentInstance,
    AgentRun,
    AgentRunEvent,
    ProtocolProfile,
    Session,
    Setting,
    User,
    Workspace,
    utcnow,
)
from app.routers.collaborations import _safe_event


@pytest.fixture
def collaboration_db():
    """复制 P1 相关 DDL 到共享 SQLite 连接；JSONB 只在测试 DDL 中转为 JSON。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    models = (
        User, Workspace, Session, ProtocolProfile, Setting, AgentCollaboration,
        AgentInstance, AgentRun, AgentRunEvent, AgentCommandReceipt,
    )
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(id="u1", username="subagent-test", password_hash="hash"))
        db.add(Session(id="s1", user_id="u1", title="协作", engine_version="agent_loop_v2"))
        db.add(ProtocolProfile(
            id="p1", name="测试模型", protocol="openai_chat", base_url="https://example.invalid",
            model="test-model", usages=["agent"], encrypted_key="cipher",
        ))
        db.add(Setting(key="agent_profile_id", value="p1"))
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


def test_subagent_registry_has_exact_p1_tools():
    """P1 只登记六个已接线工具，send 与工作项留在后续阶段。"""
    registry = build_default_registry()
    register_subagent_tools(registry)
    names = {name for name in registry.names() if name.startswith("agent.")}
    assert names == {
        "agent.list", "agent.spawn", "agent.status", "agent.wait", "agent.result", "agent.cancel",
    }


def test_run_event_projection_removes_reasoning_and_protocol_state():
    """运行记录可展示成果摘要，但不能把原始思考或供应商 opaque 状态发给浏览器。"""
    projected = _safe_event({
        "seq": 3,
        "ts": 1.0,
        "type": "assistant/message",
        "run_id": "r1",
        "data": {
            "turn": 1,
            "content": "可展示结论",
            "reasoning_content": "内部思考",
            "protocol_state": {"signature": "secret"},
        },
    })
    assert projected["data"] == {"turn": 1, "content": "可展示结论"}


def test_subagent_log_orders_and_isolates_runs(collaboration_db):
    """两个 run 的 seq 都从零开始，logical_key 重放不会跨运行串线。"""
    with collaboration_db() as db:
        collaboration = AgentCollaboration(
            id="c1", session_id="s1", owner_id="u1", root_turn=1, goal="并行核对",
        )
        first = AgentInstance(
            id="i1", collaboration_id="c1", expert_id="general", expert_snapshot={},
            profile_snapshot={}, permission_snapshot={}, depth=1,
        )
        second = AgentInstance(
            id="i2", collaboration_id="c1", expert_id="general", expert_snapshot={},
            profile_snapshot={}, permission_snapshot={}, depth=1,
        )
        db.add_all([collaboration, first, second])
        db.flush()
        db.add_all([
            AgentRun(id="r1", collaboration_id="c1", instance_id="i1", goal="A", output_contract="文本"),
            AgentRun(id="r2", collaboration_id="c1", instance_id="i2", goal="B", output_contract="文本"),
        ])
        db.commit()
    one = SubagentLog("s1", "r1", collaboration_db, actor_id="u1")
    two = SubagentLog("s1", "r2", collaboration_db, actor_id="u1")
    assert one.append("turn/start", {"turn": 1}, logical_key="start")["seq"] == 0
    assert two.append("turn/start", {"turn": 1}, logical_key="start")["seq"] == 0
    assert one.append("turn/start", {"turn": 1}, logical_key="start")["seq"] == 0
    with pytest.raises(AppError):
        one.append("turn/start", {"turn": 2}, logical_key="start")
    assert len(one.read()) == len(two.read()) == 1
    assert one.read()[0]["run_id"] == "r1" and two.read()[0]["run_id"] == "r2"


@pytest.mark.asyncio
async def test_two_experts_spawn_in_parallel_and_reuse_mutation_receipt(
    collaboration_db, monkeypatch,
):
    """两个不同专家进入同一 TurnChildren 并行运行，重复 spawn 不创建第三个实例。"""
    children = TurnChildren(max_children=8)
    budget = ModelCallBudget(max_calls=80, max_concurrent=3, max_calls_per_run=20)
    service = SimpleNamespace(session_factory=collaboration_db)
    entry = SimpleNamespace(log=SimpleNamespace(session_id="s1"))
    coordinator = CollaborationCoordinator(
        service, entry, "u1", {"content": "并行检查", "profile_id": "p1"}, children, budget,
    )
    started: list[str] = []
    contracts: list[str] = []
    release = asyncio.Event()

    async def fake_run(
        run_id: str,
        expert_id: str,
        _profile_id: str,
        goal: str,
        _output_contract: str,
    ) -> None:
        """保留真实 asyncio 并行和数据库终态，替换外部模型请求。"""
        started.append(expert_id)
        contracts.append(_output_contract)
        with collaboration_db() as db:
            run = db.get(AgentRun, run_id)
            run.status = "running"
            run.started_at = utcnow()
            db.commit()
        await release.wait()
        coordinator._finish_run(run_id, "succeeded", {"content": goal, "finish_reason": "completed"})
        coordinator._refresh_collaboration()

    monkeypatch.setattr(coordinator, "_run_child", fake_run)
    args_a = {"expert_id": "general", "goal": "核对架构", "output_contract": "给出结论"}
    args_b = {"expert_id": "testcase-agent", "goal": "设计用例", "output_contract": "给出用例"}
    identity_a = {"turn": 1, "call_id": "call-a"}
    identity_b = {"turn": 1, "call_id": "call-b"}
    first = await coordinator._spawn(args_a, identity_a)
    second = await coordinator._spawn(args_b, identity_b)
    duplicate = await coordinator._spawn(args_a, identity_a)
    await asyncio.sleep(0)
    assert first == duplicate
    assert first["run_id"] != second["run_id"]
    assert set(started) == {"general", "testcase-agent"}
    assert set(contracts) == {"给出结论", "给出用例"}
    assert len(coordinator.tasks) == 2
    with collaboration_db() as db:
        assert db.query(AgentInstance).count() == 2
        assert db.query(AgentCommandReceipt).count() == 2
    release.set()
    await asyncio.gather(*coordinator.tasks.values())
    coordinator._refresh_collaboration()
    with collaboration_db() as db:
        assert db.get(AgentCollaboration, first["collaboration_id"]).status == "succeeded"
        assert {row.status for row in db.query(AgentRun).all()} == {"succeeded"}
    await children.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during_cleanup", [False, True])
async def test_wait_publishes_terminal_only_after_cleanup(
    collaboration_db, monkeypatch, cancel_during_cleanup,
):
    """模型已完成但连接尚未释放时仍为运行中；重复停止不能截断清理。"""
    from app.agent import collaboration, loop, loop_wiring

    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()
    prompts = []

    class CompletedRuntime:
        """替换供应商模型，保留协调器、日志、查询和关闭时序。"""

        def __init__(self, log, _graph, **_kwargs):
            """持有真实持久日志。"""
            self.log = log

        async def submit(self, content, **_kwargs):
            """直接写入模型完成记录，模拟快速供应商回复。"""
            prompts.append(content)
            self.log.append("assistant/message", {"content": "专家结论"})
            self.log.append("turn/end", {"reason": "completed"})

        async def wait(self):
            """模型在 submit 中已完成。"""

        async def close(self):
            """连接资源由服务关闭钩子模拟。"""

    async def close_resources(_resources):
        """阻塞资源清理，放大终态发布与关闭之间的竞态窗口。"""
        cleanup_started.set()
        await release_cleanup.wait()
        cleanup_finished.set()

    children = TurnChildren(max_children=8)
    service = SimpleNamespace(
        session_factory=collaboration_db, _settings=lambda: None,
        _broker=None, _close_resources=close_resources,
    )
    coordinator = CollaborationCoordinator(
        service, SimpleNamespace(log=SimpleNamespace(session_id="s1")), "u1",
        {"content": "检查", "profile_id": "p1"}, children,
        ModelCallBudget(max_calls=80, max_concurrent=3, max_calls_per_run=20),
    )
    monkeypatch.setattr(collaboration, "AgentRuntime", CompletedRuntime)
    monkeypatch.setattr(loop, "build_agent", AsyncMock(return_value=None))
    monkeypatch.setattr(loop_wiring, "build_dependencies", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(coordinator, "_child_workspace", lambda _run_id: "unused")
    identity = {"turn": 1, "call_id": "cleanup-spawn"}
    spawned = await coordinator._spawn(
        {"expert_id": "general", "goal": "检查", "output_contract": "列出依据"}, identity,
    )
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        assert "【交付要求】\n列出依据" in prompts[0]
        waiting = await coordinator._wait(
            {"run_ids": [spawned["run_id"]], "timeout_seconds": 0}, identity,
        )
        assert waiting["completed"] is False
        assert waiting["runs"][0]["status"] == "running"
        if cancel_during_cleanup:
            await coordinator.cancel_run_by_user(spawned["run_id"], "停止")
            await asyncio.sleep(0)
            await coordinator.cancel_run_by_user(spawned["run_id"], "重复停止")
        release_cleanup.set()
        await asyncio.gather(*coordinator.tasks.values(), return_exceptions=True)
        assert cleanup_finished.is_set()
        result = await coordinator._result({"run_id": spawned["run_id"]}, identity)
        assert result["available"] is True
        assert result["status"] == ("cancelled" if cancel_during_cleanup else "succeeded")
        assert result["result"]["complete"] is (not cancel_during_cleanup)
    finally:
        release_cleanup.set()
        await children.close()


@pytest.mark.asyncio
async def test_cancel_before_child_starts_settles_persistent_run(collaboration_db):
    """主回合立即收尾时，尚未执行首条语句的专家也必须从 queued 进入终态。"""
    children = TurnChildren(max_children=8)
    coordinator = CollaborationCoordinator(
        SimpleNamespace(session_factory=collaboration_db),
        SimpleNamespace(log=SimpleNamespace(session_id="s1")), "u1",
        {"content": "检查", "profile_id": "p1"}, children,
        ModelCallBudget(max_calls=80, max_concurrent=3, max_calls_per_run=20),
    )
    identity = {"turn": 1, "call_id": "early-cancel"}
    spawned = await coordinator._spawn(
        {"expert_id": "general", "goal": "检查", "output_contract": "结论"}, identity,
    )
    await coordinator.cancel_run_by_user(spawned["run_id"], "立即停止")
    await children.close()
    with collaboration_db() as db:
        assert db.get(AgentRun, spawned["run_id"]).status == "cancelled"
        assert db.get(AgentCollaboration, spawned["collaboration_id"]).status == "cancelled"


@pytest.mark.asyncio
async def test_child_setup_failure_settles_persistent_run(collaboration_db, monkeypatch):
    """图构造失败发生在模型启动前，也必须留下可查询失败且不泄露内部异常。"""
    from app.agent import loop

    monkeypatch.setattr(loop, "build_agent", AsyncMock(side_effect=RuntimeError("private detail")))
    children = TurnChildren(max_children=8)
    coordinator = CollaborationCoordinator(
        SimpleNamespace(
            session_factory=collaboration_db, _settings=lambda: None,
            _close_resources=AsyncMock(),
        ),
        SimpleNamespace(log=SimpleNamespace(session_id="s1")), "u1",
        {"content": "检查", "profile_id": "p1"}, children,
        ModelCallBudget(max_calls=80, max_concurrent=3, max_calls_per_run=20),
    )
    identity = {"turn": 1, "call_id": "setup-fail"}
    spawned = await coordinator._spawn(
        {"expert_id": "general", "goal": "检查", "output_contract": "结论"}, identity,
    )
    await asyncio.gather(*coordinator.tasks.values())
    result = await coordinator._result({"run_id": spawned["run_id"]}, identity)
    assert result["status"] == "failed"
    assert result["error_code"] == "INTERNAL"
    assert "private detail" not in str(result)
    await children.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,stop_group", [("succeeded", True), ("failed", True), ("running", False)])
async def test_cancel_without_runtime_preserves_terminal_and_aggregates(
    collaboration_db, status, stop_group,
):
    """进程重启后停止不能改写历史终态，停止最后一位专家须同步整组状态。"""
    from app.routers.collaborations import CancelRequest, cancel_agent_run, cancel_collaboration

    with collaboration_db() as db:
        db.add(AgentCollaboration(
            id="c1", session_id="s1", owner_id="u1", root_turn=1, goal="检查", status=status,
        ))
        db.add(AgentInstance(
            id="i1", collaboration_id="c1", expert_id="general", expert_snapshot={},
            profile_snapshot={}, permission_snapshot={}, depth=1,
        ))
        db.flush()
        db.add(AgentRun(
            id="r1", collaboration_id="c1", instance_id="i1", goal="检查",
            output_contract="结论", status=status,
        ))
        db.commit()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        user = db.get(User, "u1")
        if stop_group:
            result = await cancel_collaboration("c1", CancelRequest(), request, db, user)
            assert result["accepted"] is False
            assert db.get(AgentCollaboration, "c1").status == status
        else:
            result = await cancel_agent_run("r1", CancelRequest(), request, db, user)
            assert result["accepted"] is True
            assert db.get(AgentCollaboration, "c1").status == "cancelled"
            assert db.get(AgentRun, "r1").result["complete"] is False
