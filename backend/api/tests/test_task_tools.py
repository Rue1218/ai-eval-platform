"""platform.tasks 长任务 MCP 工具（P4-1）单测。

覆盖：task.create 门禁（kind/数据集/待确认卡/占槽/stress 父任务/IntegrityError）、
task.status 归属、task.cancel 终态短路、contextual 上下文透传、toolnode 占槽
门禁接线。DB 用 ``_FakeDb`` 桩 + monkeypatch ``app.db.SessionLocal``，不依赖
真实数据库连接。
"""

import asyncio

import pytest

import app.harness.execution.toolnode as toolnode_mod
from app.errors import AppError, ErrorCode
from app.harness.execution import (
    MCPClientManager,
    ToolDef,
    ToolRegistry,
    build_default_registry,
    build_tool_node,
)
from app.harness.execution.mcp import ToolExecutionContext
from app.harness.execution.task_tools import cancel_task_safe, create_task_safe, status_task_safe
from app.models import AuditLog, Task, TaskEvent
from app.models import Session as AgentSession


def _ctx(session_id: str = "s1", user_id: str = "u1", call_id: str = "c1") -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        user_id=user_id,
        thread_id="t1",
        sandbox_dir="/tmp/ws",
        call_id=call_id,
    )


class _SessionRow:
    def __init__(self, pending_confirm: dict | None = None) -> None:
        self.pending_confirm = pending_confirm


class _Query:
    """吞掉 filter 链的最小查询桩。"""

    def __init__(self, result) -> None:
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def with_for_update(self):
        return self

    def first(self):
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result

    def all(self):
        if isinstance(self._result, list):
            return self._result
        return [self._result] if self._result is not None else []

    def count(self):
        if isinstance(self._result, list):
            return len(self._result)
        return 1 if self._result is not None else 0


class _FakeDb:
    """覆盖 task_tools 所需 query/get/add/flush/commit/rollback/close 的最小会话桩。"""

    def __init__(self, *, session_row=None, tasks=None, task_query=None, fail_integrity=False):
        self._session_row = session_row
        self._tasks = dict(tasks or {})
        self._task_query = task_query
        self.fail_integrity = fail_integrity
        self.added: list = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def query(self, model):
        if model is AgentSession:
            return _Query(self._session_row)
        return _Query(self._task_query)

    def get(self, model, pk):
        if model is Task:
            return self._tasks.get(pk)
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        if self.fail_integrity:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("fake", {}, Exception("uq_tasks_active_session"))

    def commit(self):
        self.commit_calls += 1
        for obj in self.added:
            if isinstance(obj, Task):
                self._tasks[obj.id] = obj

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True


def _run_toolnode(node, state, configurable: dict) -> dict:
    class _FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            return {"configurable": configurable}.get(key, default)

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: _FakeConfig()
    try:
        return asyncio.run(node(state))
    finally:
        toolnode_mod.get_config = original


def _tool_result(out: dict) -> dict:
    return next(event for event in out["pending_events"] if event["kind"] == "tool_result")


# —— task.create 门禁 ——


def test_create_requires_context() -> None:
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "benchmark"}, None)
    assert error.value.code == ErrorCode.VALIDATION


def test_create_rejects_unknown_kind() -> None:
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "hack"}, _ctx())
    assert error.value.code == ErrorCode.VALIDATION
    assert "未知任务类型" in error.value.message


def test_create_missing_dataset(monkeypatch) -> None:
    monkeypatch.setattr("app.db.SessionLocal", lambda: _FakeDb(session_row=_SessionRow(), task_query=[]))
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "benchmark"}, _ctx())
    assert error.value.code == ErrorCode.VALIDATION
    assert "数据集" in error.value.message


def test_create_rag_requires_kb_and_gold(monkeypatch) -> None:
    monkeypatch.setattr("app.db.SessionLocal", lambda: _FakeDb(session_row=_SessionRow(), task_query=[]))
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "rag"}, _ctx())
    assert error.value.code == ErrorCode.VALIDATION
    assert "知识库" in error.value.message


def test_create_rag_ok_without_dataset(monkeypatch) -> None:
    db = _FakeDb(session_row=_SessionRow(), task_query=[])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    result = create_task_safe({"kind": "rag", "kb_id": "kb1", "gold_qa_id": "g1"}, _ctx())
    assert result["status"] == "queued"
    assert result["kind"] == "rag"


def test_create_pending_confirm_rejected(monkeypatch) -> None:
    db = _FakeDb(session_row=_SessionRow(pending_confirm={"kind": "benchmark"}), task_query=[])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "benchmark", "dataset_id": "d1"}, _ctx())
    assert error.value.code == ErrorCode.CONCURRENCY


def test_create_active_task_rejected(monkeypatch) -> None:
    active = Task(id="t-active", kind="benchmark", status="running", config={}, created_by="u1", session_id="s1")
    db = _FakeDb(session_row=_SessionRow(), task_query=[active])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "benchmark", "dataset_id": "d1"}, _ctx())
    assert error.value.code == ErrorCode.CONCURRENCY


def test_create_stress_requires_succeeded_parent(monkeypatch) -> None:
    parent = Task(id="parent", kind="benchmark", status="running", config={}, created_by="u1")
    db = _FakeDb(session_row=_SessionRow(), task_query=[], tasks={"parent": parent})
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "stress", "parent_task_id": "parent"}, _ctx())
    assert error.value.code == ErrorCode.VALIDATION


def test_create_stress_with_succeeded_benchmark_parent(monkeypatch) -> None:
    parent = Task(id="parent", kind="benchmark", status="succeeded", config={}, created_by="u1")
    db = _FakeDb(session_row=_SessionRow(), task_query=[], tasks={"parent": parent})
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    result = create_task_safe({"kind": "stress", "parent_task_id": "parent"}, _ctx())
    assert result["status"] == "queued"
    assert result["kind"] == "stress"
    assert result["task_id"]


def test_create_ok_enqueues_with_spec_and_owner(monkeypatch) -> None:
    db = _FakeDb(session_row=_SessionRow(), task_query=[])
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    result = create_task_safe(
        {"kind": "benchmark", "dataset_id": "d1", "profile_ids": ["p1"]},
        _ctx(),
    )
    assert result["status"] == "queued"
    assert result["kind"] == "benchmark"
    assert db.commit_calls >= 1
    task = db._tasks[result["task_id"]]
    assert task.config == {"dataset_id": "d1", "profile_ids": ["p1"]}
    assert task.created_by == "u1"
    assert task.session_id == "s1"
    assert task.status == "queued"


def test_create_integrity_conflict_returns_concurrency(monkeypatch) -> None:
    db = _FakeDb(session_row=_SessionRow(), task_query=[], fail_integrity=True)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError) as error:
        create_task_safe({"kind": "benchmark", "dataset_id": "d1"}, _ctx())
    assert error.value.code == ErrorCode.CONCURRENCY
    assert db.rollback_calls >= 1


# —— task.status ——


def test_status_not_found(monkeypatch) -> None:
    monkeypatch.setattr("app.db.SessionLocal", lambda: _FakeDb(tasks={}))
    with pytest.raises(AppError) as error:
        status_task_safe({"task_id": "nope"}, _ctx())
    assert error.value.code == ErrorCode.NOT_FOUND


def test_status_unauthorized(monkeypatch) -> None:
    task = Task(id="t1", kind="benchmark", status="running", config={}, created_by="other")
    monkeypatch.setattr("app.db.SessionLocal", lambda: _FakeDb(tasks={"t1": task}))
    with pytest.raises(AppError) as error:
        status_task_safe({"task_id": "t1"}, _ctx())
    assert error.value.code == ErrorCode.UNAUTHORIZED


def test_status_ok(monkeypatch) -> None:
    task = Task(
        id="t1",
        kind="rag",
        status="queued",
        config={},
        progress={"done": 1, "total": 2, "message": "检索中"},
        created_by="u1",
        report_id=None,
    )
    monkeypatch.setattr("app.db.SessionLocal", lambda: _FakeDb(tasks={"t1": task}))
    result = status_task_safe({"task_id": "t1"}, _ctx())
    assert result["task_id"] == "t1"
    assert result["kind"] == "rag"
    assert result["status"] == "queued"
    assert result["progress"] == {"done": 1, "total": 2, "message": "检索中"}


# —— task.cancel ——


def test_cancel_terminal_short_circuit(monkeypatch) -> None:
    task = Task(id="t1", kind="benchmark", status="succeeded", config={}, created_by="u1")
    db = _FakeDb(tasks={"t1": task}, task_query=task)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    result = cancel_task_safe({"task_id": "t1"}, _ctx())
    assert result["status"] == "succeeded"
    assert db.commit_calls == 0


def test_cancel_ok_marks_cancelled_with_events(monkeypatch) -> None:
    task = Task(id="t1", kind="benchmark", status="running", config={}, created_by="u1")
    db = _FakeDb(tasks={"t1": task}, task_query=task)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    result = cancel_task_safe({"task_id": "t1"}, _ctx())
    assert result["status"] == "cancelled"
    assert task.status == "cancelled"
    assert task.finished_at is not None
    assert any(isinstance(obj, TaskEvent) and obj.event == "cancelled" for obj in db.added)
    assert any(isinstance(obj, AuditLog) and obj.action == "task_cancel" for obj in db.added)


def test_cancel_unauthorized(monkeypatch) -> None:
    task = Task(id="t1", kind="benchmark", status="running", config={}, created_by="other")
    monkeypatch.setattr("app.db.SessionLocal", lambda: _FakeDb(tasks={"t1": task}, task_query=task))
    with pytest.raises(AppError) as error:
        cancel_task_safe({"task_id": "t1"}, _ctx())
    assert error.value.code == ErrorCode.UNAUTHORIZED


# —— contextual 上下文透传 ——


def test_contextual_handler_receives_execution_context() -> None:
    captured: dict = {}

    def handler(arguments: dict, sandbox_dir: str | None = None, context: object | None = None) -> str:
        captured["context"] = context
        return "ok"

    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="tctx",
            description="上下文工具",
            parameters_schema={},
            permission="p",
            timeout_s=5.0,
            handler=handler,
            server_id="platform.custom",
            contextual=True,
        )
    )
    manager = MCPClientManager.build_from_registry(registry)
    context = _ctx(call_id="c-ctx")
    result = asyncio.run(manager.call_tool("platform.custom.tctx", {}, context))
    assert result.ok is True
    assert captured["context"] is context


def test_non_contextual_handler_two_args_via_manager() -> None:
    """非 contextual 2 参 handler 经 manager 调用仍兼容（回归）。"""
    captured: dict = {}

    def handler(arguments: dict, sandbox_dir: str | None = None) -> str:
        captured["sandbox_dir"] = sandbox_dir
        return "ok"

    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="plain",
            description="普通工具",
            parameters_schema={},
            permission="p",
            timeout_s=5.0,
            handler=handler,
            server_id="platform.custom",
        )
    )
    manager = MCPClientManager.build_from_registry(registry)
    result = asyncio.run(manager.call_tool("platform.custom.plain", {}, _ctx()))
    assert result.ok is True
    assert captured["sandbox_dir"] == "/tmp/ws"


# —— toolnode 占槽门禁接线 ——


def test_toolnode_task_create_rejected_when_active_task() -> None:
    registry = build_default_registry()
    active = Task(id="t-active", kind="benchmark", status="running", config={}, created_by="u1", session_id="s1")
    db = _FakeDb(session_row=_SessionRow(), task_query=[active])
    node = build_tool_node(
        registry,
        manager=MCPClientManager.build_from_registry(registry),
        db_factory=lambda: db,
    )
    state = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "task.create", "arguments": {"kind": "benchmark", "dataset_id": "d1"}},
    }
    configurable = {"session": {"id": "s1"}, "credentials": {"user_id": "u1"}, "thread_id": "t1"}
    out = _run_toolnode(node, state, configurable)
    payload = _tool_result(out)["payload"]
    assert payload["ok"] is False
    assert payload["error"] == "会话存在活动任务"


def test_toolnode_task_status_passes_gate_without_active_task(monkeypatch) -> None:
    """task.status 无活动任务时通过占槽门禁（占槽只拦再入队 task.create）。"""
    registry = build_default_registry()
    db = _FakeDb(session_row=_SessionRow(), task_query=[])
    # task.status 处理器自管 Session：monkeypatch app.db.SessionLocal（lazy import）
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    node = build_tool_node(
        registry,
        manager=MCPClientManager.build_from_registry(registry),
        db_factory=lambda: db,
    )
    state = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "task.status", "arguments": {"task_id": "missing"}},
    }
    configurable = {"session": {"id": "s1"}, "credentials": {"user_id": "u1"}, "thread_id": "t1"}
    out = _run_toolnode(node, state, configurable)
    payload = _tool_result(out)["payload"]
    # 无活动任务 → 门禁通过 → 进入执行 → 任务不存在 → NOT_FOUND
    assert payload["ok"] is False
    assert payload["error"] == "操作失败（NOT_FOUND）"


def test_toolnode_task_cancel_passes_gate_with_active_task(monkeypatch) -> None:
    """task.cancel 有活动任务时仍通过占槽门禁（取消正是为释放占槽）。"""
    registry = build_default_registry()
    task = Task(id="t1", kind="benchmark", status="running", config={}, created_by="u1")
    db = _FakeDb(session_row=_SessionRow(), task_query=[task], tasks={"t1": task})
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    node = build_tool_node(
        registry,
        manager=MCPClientManager.build_from_registry(registry),
        db_factory=lambda: db,
    )
    state = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "task.cancel", "arguments": {"task_id": "t1"}},
    }
    configurable = {"session": {"id": "s1"}, "credentials": {"user_id": "u1"}, "thread_id": "t1"}
    out = _run_toolnode(node, state, configurable)
    payload = _tool_result(out)["payload"]
    assert payload["ok"] is True
    assert '"status": "cancelled"' in payload["data"]["summary"]
