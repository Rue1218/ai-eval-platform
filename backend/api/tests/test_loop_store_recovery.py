"""只在明确指定的隔离 PostgreSQL 上验证存储与恢复衔接。"""

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.config import Settings, settings
from app.errors import AppError
from app.harness.memory.agent_events import SessionLog, SessionLogWriteError
from app.harness.memory.agent_recovery import recovery_events
from app.models import (
    AgentEvent,
    AgentRuntimeState,
    Base,
    Message,
    Report,
    Session,
    SessionStream,
    Task,
    User,
    Workspace,
    WorkspaceExecutionGuard,
    WsEvent,
)


def _validate_test_database_url(url, *production_urls):
    """要求显式 PostgreSQL 测试目标，并拒绝配置中的业务库端点及系统库。"""
    parsed = make_url(url)

    def endpoint(value):
        """比较实际库端点，忽略凭据、驱动名及本机地址别名。"""
        host = value.host or "localhost"
        if host in {"localhost", "127.0.0.1", "::1"}:
            host = "localhost"
        return host, value.port or 5432, value.database

    if (parsed.get_backend_name() != "postgresql" or not parsed.database
            or parsed.database in {"postgres", "template0", "template1"}
            or any(endpoint(parsed) == endpoint(make_url(value)) for value in production_urls)):
        raise ValueError("必须显式指定独立 PostgreSQL 测试库，不能使用业务库或系统库")


@pytest.mark.parametrize("url,allowed", [
    ("postgresql://tester@ci-postgres:5432/loop_ci", True),
    ("postgresql://tester@127.0.0.1:55439/looptest", True),
    ("postgresql://tester@127.0.0.1:5432/aieval", False),
    ("postgresql://tester@ci-postgres:5432/postgres", False),
    ("sqlite:///looptest", False),
])
def test_test_database_target_validation(url, allowed):
    """CI 可自行指定测试端口和库名，但换用户不能绕过业务库拒绝规则。"""
    production_url = "postgresql://app@localhost:5432/aieval"
    if allowed:
        _validate_test_database_url(url, production_url)
    else:
        with pytest.raises(ValueError):
            _validate_test_database_url(url, production_url)


@pytest.fixture
def pg():
    """仅创建并删除本例随机 schema，不操作 public、主数据库或其他测试数据。"""
    url = os.environ.get("LOOP_STORE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要显式 LOOP_STORE_TEST_DATABASE_URL")
    try:
        _validate_test_database_url(
            url, settings.database_url, Settings.model_fields["database_url"].default,
        )
    except ValueError:
        pytest.fail("LOOP_STORE_TEST_DATABASE_URL 必须指定独立 PostgreSQL 测试库")
    schema = "loop_store_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    factory = sessionmaker(engine)
    logs = []
    try:
        Base.metadata.create_all(engine, tables=[model.__table__ for model in (
            User, Workspace, Session, Message, AgentRuntimeState, AgentEvent,
            SessionStream, WorkspaceExecutionGuard, Task, Report, WsEvent,
        )])
        ids = [str(uuid4()), str(uuid4())]
        with factory.begin() as db:
            db.add(User(id="actor", username="actor", password_hash="not-a-login"))
            db.flush()
            db.add_all([Session(id=sid, user_id="actor", engine_version="agent_loop_v2")
                        for sid in ids])

        def log(index=0, claim=True):
            """每个句柄独立持有 PG writer；跨 schema 也使用唯一 session_id。"""
            value = SessionLog(ids[index], factory, actor_id="actor")
            logs.append(value)
            if claim:
                value.claim()
            return value

        yield log, factory, control
    finally:
        for value in logs:
            value.close()
        engine.dispose()
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def call(log, *, execution_id="exec-a", scope="/workspace/a"):
    """登记调用及带 guard 的派发边界。"""
    base = {"turn": 1, "step": 1, "attempt_id": "attempt", "call_id": "call", "name": "read"}
    recorded = log.append("tool/call", {**base, "args": {}})
    base["call_seq"] = recorded["seq"]
    log.append("tool/dispatch", {**base, "execution_id": execution_id,
                                "scope_path": scope, "access": "read"})
    return base


def result(base, status="succeeded", **extra):
    """规范工具结果与唯一派发身份。"""
    return {**base, "status": status, "content": "result", "is_error": status != "succeeded", **extra}


def test_zero_seq_atomic_turn_receipt_and_duplicate_client_input(pg):
    """首条事实从零开始，输入和回执同事务，重复提交返回原始事实。"""
    create, factory, _ = pg
    log = create()
    log.command_context = {"request_id": "r", "fingerprint": "f",
                           "attachment_refs": [{"id": "file"}]}
    data = {"turn": 1, "content": "hello", "client_message_id": "client"}
    started, user = log.begin_turn(data, writer_id=log.writer_id)
    assert started["seq"] == 0 and user["seq"] == 1
    assert user["extensions"]["actor_id"] == "actor"
    assert user["extensions"]["input_fingerprint"] == "f"
    assert log.command_receipt("actor", "r")["data"]["turn"] == 1
    assert log.begin_turn(data, writer_id=log.writer_id) == (started, user)
    assert len(log.read()) == 3 and log.next_seq == 3
    with factory() as db:
        assert len(list(db.scalars(select(Message)))) == 1
    with pytest.raises(AppError):
        log.begin_turn({**data, "content": "different"}, writer_id=log.writer_id)


def test_atomic_projection_failure_rolls_back_all_counters(pg, monkeypatch):
    """中途投影失败不留下半个回合、消息或跳号的游标。"""
    from app.agent import events

    create, factory, _ = pg
    log = create()
    project = events.project_fact

    def fail(event):
        if event["type"] == "user/message":
            raise RuntimeError("projection unavailable")
        return project(event)

    monkeypatch.setattr(events, "project_fact", fail)
    with pytest.raises(RuntimeError):
        log.begin_turn({"content": "hello"})
    assert log.read() == [] and log.high_water() == 0
    with factory() as db:
        state = db.get(AgentRuntimeState, log.session_id)
        assert state.next_seq == 0 and state.active_turn is None and state.last_turn == 0
        assert not list(db.scalars(select(Message)))


def test_claim_excludes_second_writer_and_invalidated_connection_cannot_write(pg):
    """第二 writer 被拒，原连接失效后不得透明重连并沿用旧 writer_id。"""
    create, _, _ = pg
    owner, other = create(), create(claim=False)
    with pytest.raises(AppError):
        other.claim()
    owner._owner_connection.invalidate()
    with pytest.raises((AppError, SessionLogWriteError)):
        owner.append("session/updated", {"title": "lost lock"})
    other.claim()
    other.append("session/updated", {"title": "new owner"})
    assert owner.read()[0]["data"]["title"] == "new owner"


def test_write_transaction_uses_the_connection_holding_advisory_lock(pg, monkeypatch):
    """事实提交和 advisory lock 处于同一物理 PG 连接，消除探活后断连窗口。"""
    create, _, _ = pg
    log = create()
    owner = log._owner_connection
    pid = owner.execute(text("SELECT pg_backend_pid()")).scalar_one()
    owner.commit()
    original = log._project_message

    def probe(db, event):
        assert db.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
        return original(db, event)

    monkeypatch.setattr(log, "_project_message", probe)
    log.begin_turn({"content": "hello"})


@pytest.mark.parametrize("invalid", ["unknown_status", "wrong_call_seq"])
def test_guard_rejects_invalid_result_without_releasing(pg, invalid):
    """非法六态或错误调用序号不能解除另一执行的 guard。"""
    create, factory, _ = pg
    log = create()
    base = call(log)
    value = result(base)
    if invalid == "unknown_status":
        value["status"] = "queued"
    else:
        value["call_seq"] += 10
    before = log.read()
    with pytest.raises(AppError):
        log.append("tool/result", value)
    assert log.read() == before
    with factory() as db:
        assert db.get(WorkspaceExecutionGuard, "exec-a").status == "active"


def test_unknown_recovery_quarantine_and_evidence_bound_reconcile(pg):
    """未知工具保持跨会话隔离，对账事实包含与原执行绑定的可信证据。"""
    create, factory, _ = pg
    log = create()
    base = call(log)
    log.append("tool/result", result(base, "outcome_unknown"))
    assert log.read()[-1]["type"] == "execution/quarantined"
    evidence = {"execution_id": "other", "status": "cancelled", "process_tree_terminated": True,
                "termination_evidence": "cgroup_empty"}
    with pytest.raises(AppError):
        log.reconcile_execution("exec-a", evidence)
    evidence["execution_id"] = "exec-a"
    log.reconcile_execution("exec-a", evidence)
    reconciled = log.read()[-1]
    assert reconciled["type"] == "execution/reconciled"
    assert reconciled["data"]["evidence"] == evidence
    count = len(log.read())
    log.reconcile_execution("exec-a", evidence)
    assert len(log.read()) == count
    with factory() as db:
        assert db.get(WorkspaceExecutionGuard, "exec-a").status == "released"


@pytest.mark.parametrize("asked,ended", [
    ("approval/asked", "approval/decided"),
    ("question/asked", "question/answered"),
    ("task_confirmation/requested", "task_confirmation/resolved"),
])
def test_recovery_clears_exact_pending_card_in_same_transaction(pg, asked, ended):
    """源恢复计划追加交互终态时，同事务清除 pending_confirm。"""
    create, factory, _ = pg
    log = create()
    log.begin_turn({"content": "hello"})
    identity = {"turn": 1, "step": 1, "attempt_id": "a", "call_id": "c",
                "interaction_id": "i", "nonce": "n"}
    log.append(asked, identity)
    with factory() as db:
        assert db.get(Session, log.session_id).pending_confirm["interaction_id"] == "i"
    for repair in recovery_events(log.read()):
        log.append(repair.type, repair.data)
    with factory() as db:
        assert db.get(Session, log.session_id).pending_confirm is None
    assert sum(e["type"] == ended for e in log.read()) == 1


def test_worker_actual_report_and_error_paths_emit_terminal_once(pg):
    """Worker 仅发 progress/report 或 error，桥仍根据持久 Task 生成真实终态。"""
    create, factory, _ = pg
    log = create()
    with factory.begin() as db:
        db.add_all([
            Task(id="success", session_id=log.session_id, kind="benchmark", status="succeeded",
                 report_id="report", created_by="actor"),
            Task(id="failed", session_id=log.session_id, kind="rag", status="failed", created_by="actor"),
        ])
        db.add_all([
            WsEvent(session_id=log.session_id, task_id="success", event_id=1, event="progress",
                    payload={"percent": 100, "done": 8, "total": 8, "message": "finished"}),
            WsEvent(session_id=log.session_id, task_id="success", event_id=2, event="report",
                    payload={"report_id": "report"}),
            WsEvent(session_id=log.session_id, task_id="failed", event_id=3, event="error",
                    payload={"code": "UPSTREAM"}),
        ])
    log.bridge_worker()
    frames = log.stream()
    terminals = [f for f in frames if f["type"] == "task.end"]
    assert {(f["correlation"]["task_id"], f["data"]["status"]) for f in terminals} == {
        ("success", "succeeded"), ("failed", "failed"),
    }
    assert next(f for f in frames if f["type"] == "task.progress")["data"]["progress"]["percent"] == 100
    log.bridge_worker()
    assert log.stream() == frames
    assert [f["cursor"] for f in frames] == list(range(1, len(frames) + 1))


def test_snapshot_contains_tool_and_task_readmodels_at_same_high_water(pg):
    """快照由 H 内的已提交流重建卡片，不能读取尚未桥接的未来任务状态。"""
    create, factory, _ = pg
    log = create()
    log.begin_turn({"content": "hello", "client_message_id": "c"})
    base = call(log)
    log.append("tool/result", result(base))
    log.append("task/queued", {"turn": 1, "task_id": "task", "status": "queued"})
    cursor, snapshot = log.snapshot()
    assert cursor == log.high_water()
    assert snapshot["tools"][0]["status"] == "succeeded"
    assert snapshot["tasks"][0]["task_id"] == "task"
    assert snapshot["tasks"][0]["status"] == "queued"
    before = deepcopy(snapshot)
    with factory.begin() as db:
        db.add(Task(id="task", session_id=log.session_id, kind="rag",
                    status="succeeded", created_by="actor"))
    assert log.snapshot() == (cursor, before)


def test_trace_pagination_includes_seq_zero_and_is_bounded(pg):
    """首条 seq=0 可读，分页参数下推数据库且保持严格升序。"""
    create, _, _ = pg
    log = create()
    for index in range(5):
        log.append("session/updated", {"title": str(index)})
    assert [e["seq"] for e in log.read(-1, limit=2)] == [0, 1]
    assert [e["seq"] for e in log.read(1, limit=2)] == [2, 3]
    assert [e["seq"] for e in log.read(3, limit=2)] == [4]


def test_backend_termination_mid_transaction_rolls_back_and_new_writer_can_claim(pg, monkeypatch):
    """物理断连发生在事实提交中途时，全组输入回滚，新进程可明确接管。"""
    create, _, control = pg
    log = create()
    original = log._project_message

    def kill(db, event):
        if event["type"] == "user/message":
            with control.begin() as killer:
                assert killer.execute(text("SELECT pg_terminate_backend(:pid)"),
                                      {"pid": log._owner_pid}).scalar_one()
        return original(db, event)

    monkeypatch.setattr(log, "_project_message", kill)
    with pytest.raises(SQLAlchemyError):
        log.begin_turn({"content": "lost"})
    assert log.read() == []
    new = create()
    assert new.begin_turn({"content": "new"})[0]["seq"] == 0


@pytest.mark.parametrize("status", [
    "succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown",
])
def test_each_result_status_preserves_exact_guard_link_and_is_idempotent(pg, status):
    """六态逐一验证：未知隔离，其余已知本地终态释放，重复结果不重复取号。"""
    create, factory, _ = pg
    log = create()
    base = call(log)
    written = log.append("tool/result", result(base, status))
    count, cursor = log.next_seq, log.high_water()
    assert log.append("tool/result", result(base, status)) == written
    assert (log.next_seq, log.high_water()) == (count, cursor)
    with factory() as db:
        guard = db.get(WorkspaceExecutionGuard, "exec-a")
        assert guard.status == ("quarantined" if status == "outcome_unknown" else "released")
        assert guard.evidence["call_seq"] == base["call_seq"]


def test_legacy_quarantine_blocks_new_read_and_never_releases_from_new_result(pg):
    """遗留执行遵守相同全局锁与 scope；新循环不能借相同 call_id 解除它。"""
    create, factory, _ = pg
    log = create()
    from app.harness.memory.agent_events import canonical_scope

    with factory.begin() as db:
        db.add(WorkspaceExecutionGuard(
            execution_id="legacy", session_id=log.session_id, scope_path=canonical_scope("/workspace/a"),
            access="write", status="quarantined", attempt_id="legacy", call_id="c",
            owner_id="actor", evidence={"engine": "legacy"},
        ))
    with pytest.raises(AppError):
        call(log)
    log.append("tool/result", {
        "turn": 1, "attempt_id": "legacy", "call_id": "c", "name": "read",
        "status": "succeeded", "is_error": False, "content": "not that execution",
    })
    with factory() as db:
        assert db.get(WorkspaceExecutionGuard, "legacy").status == "quarantined"


def test_wrong_interaction_nonce_rolls_back_terminal_projection(pg):
    """同名 interaction 不足以清卡，nonce 错误时事实与游标全部回滚。"""
    create, _, _ = pg
    log = create()
    log.begin_turn({"content": "hello"})
    identity = {"turn": 1, "step": 1, "attempt_id": "a", "call_id": "c",
                "interaction_id": "i", "nonce": "right"}
    log.append("question/asked", identity)
    before = (log.read(), log.high_water())
    with pytest.raises(AppError):
        log.append("question/answered", {**identity, "nonce": "wrong", "outcome": "cancelled"})
    assert (log.read(), log.high_water()) == before


def test_worker_backlog_and_late_outbox_do_not_duplicate_or_reopen_terminal(pg):
    """分页追平后才补终态，丢失 WS 报告可补齐，晚到报告不再重复或逆转任务。"""
    create, factory, _ = pg
    log = create()
    with factory.begin() as db:
        db.add(Task(id="t", session_id=log.session_id, kind="rag", status="succeeded",
                    created_by="actor", report_id="r"))
        for index in (1, 2):
            db.add(WsEvent(session_id=log.session_id, task_id="t", event_id=index,
                           event="progress", payload={"percent": index * 50}))
    log.bridge_worker(limit=1)
    assert not any(f["type"] == "task.end" for f in log.stream())
    log.bridge_worker(limit=1)
    frames = log.stream()
    assert [f["type"] for f in frames][-2:] == ["task.report", "task.end"]
    with factory.begin() as db:
        db.add_all([
            WsEvent(session_id=log.session_id, task_id="t", event_id=3,
                    event="report", payload={"report_id": "r"}),
            WsEvent(session_id=log.session_id, task_id="t", event_id=4,
                    event="progress", payload={"percent": 100}),
        ])
    log.bridge_worker()
    assert log.stream() == frames


def test_worker_awaiting_case_confirmation_is_not_terminal(pg):
    """用例生成百分百但仍待确认时，只更新任务进展，不伪造完成。"""
    create, factory, _ = pg
    log = create()
    with factory.begin() as db:
        db.add(Task(id="t", session_id=log.session_id, kind="testcase",
                    status="awaiting_case_confirm", created_by="actor"))
        db.add(WsEvent(session_id=log.session_id, task_id="t", event_id=1,
                       event="progress", payload={"percent": 100, "done": 4, "total": 4}))
    log.bridge_worker()
    assert [event["type"] for event in log.stream()] == ["task.progress"]
    assert log.stream()[0]["data"]["status"] == "awaiting_case_confirm"
    assert log.snapshot()[1]["tasks"][0]["status"] == "awaiting_case_confirm"


def test_remote_known_result_requires_original_runner_stop_evidence(pg):
    """远端自称成功不足以释放 guard，收据还必须匹配实例及请求指纹。"""
    create, factory, _ = pg
    log = create()
    base = {"turn": 1, "step": 1, "attempt_id": "a", "call_id": "c", "name": "bash"}
    event = log.append("tool/call", {**base, "args": {}})
    base["call_seq"] = event["seq"]
    log.append("tool/dispatch", {
        **base, "execution_id": "e", "scope_path": "/remote", "access": "write",
        "runner_instance_id": "runner", "request_fingerprint": "request",
    })
    with pytest.raises(AppError):
        log.append("tool/result", result(base))
    receipt = {
        "execution_id": "e", "runner_instance_id": "runner", "request_fingerprint": "request",
        "process_tree_terminated": True, "termination_evidence": "cgroup_empty",
    }
    with pytest.raises(AppError):
        log.append("tool/result", result(base, metadata={**receipt, "request_fingerprint": "wrong"}))
    log.append("tool/result", result(base, metadata=receipt))
    with factory() as db:
        assert db.get(WorkspaceExecutionGuard, "e").status == "released"


@pytest.mark.asyncio
async def test_pg_known_enqueue_recovers_succeeded_and_closes_confirmation(pg):
    """PG 已知入队收据恢复为真实成功，重启不重放创建任务副作用。"""
    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from app.harness.memory.agent_messages import derive_messages

    create, factory, _ = pg
    log = create()
    log.begin_turn({"content": "评测"})
    identity = {"turn": 1, "step": 1, "attempt_id": "a", "call_id": "c"}
    log.append("assistant/message", {
        **identity, "message": {"role": "assistant", "content": "",
                               "tool_calls": [{"id": "c", "name": "task.create", "args": {}}]},
    })
    card = {**identity, "interaction_id": "confirmation", "nonce": "nonce"}
    log.append("task_confirmation/requested", card)
    # 模拟 enqueue 与收据同事务提交后、tool/result 提交前崩溃。
    with log._transaction() as (db, session, state):
        db.add(Task(id="queued", session_id=log.session_id, kind="rag",
                    status="queued", created_by="actor"))
        log._append(db, session, state, "task/queued", {
            **identity, "task_id": "queued", "content": "已入队 queued",
        })
    log.close()
    reopened = create()
    runtime = AgentRuntime(reopened, await build_agent(LoopSettings()))
    await runtime.recover()
    message = derive_messages(reopened.read())[-1]
    assert message["content"] == "已入队 queued" and message["is_error"] is False
    with factory() as db:
        assert len(list(db.scalars(select(Task)))) == 1
        assert db.get(Session, log.session_id).pending_confirm is None
    terminal = next(e for e in reopened.read() if e["type"] == "task_confirmation/resolved")
    assert terminal["data"]["decision"] == "cancelled"
    assert await runtime.recover() == []
    await runtime.close()


@pytest.mark.asyncio
async def test_pg_history_selection_replays_exact_trimmed_input_after_restart(pg):
    """按 A08 从重启后的事实前缀和索引，逐字段重建实际 SDK 输入。"""
    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from app.harness.memory.agent_messages import derive_messages
    from app.llm.loop_contracts import Done, TextDelta
    from tests.test_loop_runtime import ScriptedAdapter, request

    create, _, _ = pg
    log = create()
    adapter = ScriptedAdapter([TextDelta("first"), Done("stop")],
                              [TextDelta("second"), Done("stop")])

    def factory(messages, effort):
        """只保留当前完整 user 回合，返回规范历史的严格后缀。"""
        start = max(i for i, message in enumerate(messages) if message["role"] == "user")
        return replace(request(), messages=messages[start:])

    graph = await build_agent(LoopSettings(), adapter=adapter, request_factory=factory)
    runtime = AgentRuntime(log, graph, actor_id="actor", writer_id=log.writer_id)
    await runtime.submit("one")
    await runtime.wait()
    await runtime.submit("two")
    await runtime.wait()
    await runtime.close()
    log.close()
    reopened = create()
    starts = [event for event in reopened.read() if event["type"] == "assistant/attempt_start"]
    assert len(starts) == 2
    for event, actual in zip(starts, adapter.requests, strict=True):
        data = event["data"]
        complete = derive_messages(reopened.read(through=data["history_upto_seq"]))
        selection = data["history_selection"]
        restored = [complete[index] for index in selection["indices"]]
        assert selection["message_count"] == len(complete)
        assert restored == actual.messages
        assert selection["input_fingerprint"] == hashlib.sha256(
            json.dumps(restored, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert data["fingerprint_algorithm"] == "dsh-json-v1"
    assert starts[-1]["data"]["history_selection"]["indices"] == [2]
