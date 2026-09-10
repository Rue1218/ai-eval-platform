"""P4-2 熔断/度量/资源配额/取消传播单测。

覆盖：ToolMetrics 计数与熔断（阈值/冷却/业务错误不计入）、MCPClientManager
熔断快速拒绝与度量记录、task.create 资源配额拒绝 + 审计、REST create_task 同
规则、worker is_cancelled。DB 用 _FakeDb 桩 + monkeypatch，不依赖真实数据库。
"""

import asyncio

import pytest

import app.harness.execution.mcp.metrics as metrics_mod
from app.errors import AppError, ErrorCode
from app.harness.execution import (
    MCPClientManager,
    ToolDef,
    ToolRegistry,
    build_default_registry,
)
from app.harness.execution.mcp import ToolExecutionContext, ToolMetrics
from app.harness.execution.task_tools import create_task_safe
from app.harness.execution.worker_bridge import count_active_tasks
from app.models import AuditLog, Dataset, ProtocolProfile, Task
from app.models import Session as AgentSession

# —— 工具桩与假时钟 ——


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _ctx(**overrides: object) -> ToolExecutionContext:
    base: dict[str, object] = {
        "session_id": "s1",
        "user_id": "u1",
        "thread_id": "t1",
        "call_id": "c1",
    }
    base.update(overrides)
    return ToolExecutionContext(**base)  # type: ignore[arg-type]


def _boom_handler(message: str = "secret internal"):
    def handler(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        raise RuntimeError(message)

    return handler


def _ok_handler(value: str = "ok"):
    def handler(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        return value

    return handler


def _registry_with(server_id: str = "platform.custom") -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="boom",
            description="爆炸工具",
            parameters_schema={},
            permission="p",
            timeout_s=5.0,
            handler=_boom_handler(),
            server_id=server_id,
            output_schema={},
        )
    )
    registry.register(
        ToolDef(
            name="ok",
            description="正常工具",
            parameters_schema={},
            permission="p",
            timeout_s=5.0,
            handler=_ok_handler(),
            server_id=server_id,
            output_schema={},
        )
    )
    return registry


class _Query:
    """吞掉 filter 链的最小查询桩；all/count/first 可分别配置。"""

    def __init__(self, all_result, count_result: int = 0, first_result=None) -> None:
        self._all_result = all_result
        self._count_result = count_result
        self._first_result = first_result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def with_for_update(self):
        return self

    def first(self):
        if self._first_result is not None:
            return self._first_result
        if isinstance(self._all_result, list):
            return self._all_result[0] if self._all_result else None
        return self._all_result

    def all(self):
        if isinstance(self._all_result, list):
            return self._all_result
        return [self._all_result] if self._all_result is not None else []

    def count(self):
        return self._count_result


class _SessionRow:
    def __init__(self, pending_confirm: dict | None = None) -> None:
        self.pending_confirm = pending_confirm


class _FakeDb:
    """覆盖 task_tools / count_active_tasks / is_cancelled 所需 query/get 的最小桩。"""

    def __init__(
        self,
        *,
        session_row=None,
        tasks=None,
        task_query=None,
        task_count=0,
        task_first=None,
        dataset=None,
        profiles=None,
    ):
        self._session_row = session_row
        self._tasks = dict(tasks or {})
        self._profiles = dict(profiles or {})
        self._task_query = task_query
        self._task_count = task_count
        self._task_first = task_first
        self._dataset = dataset if dataset is not None else Dataset(id="d1", name="测试数据集")
        self.added: list = []
        self.commit_calls = 0

    def query(self, model):
        if model is AgentSession:
            return _Query(self._session_row)
        if model is Dataset:
            return _Query(self._dataset)
        return _Query(self._task_query, self._task_count, first_result=self._task_first)

    def get(self, model, pk):
        if model is Task:
            return self._tasks.get(pk)
        if model is ProtocolProfile:
            return self._profiles.get(pk)
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        pass

    def close(self):
        pass


# —— ToolMetrics 计数与熔断 ——


def test_metrics_counts_success_failure_timeout() -> None:
    metrics = ToolMetrics()
    metrics.record_call("read", "platform.files", ok=True, latency_ms=10)
    metrics.record_call("read", "platform.files", ok=True, latency_ms=30)
    metrics.record_call("bash", "platform.sandbox", ok=False, timeout=True, error_code="TIMEOUT", latency_ms=500)
    metrics.record_call("bash", "platform.sandbox", ok=False, error_code="VALIDATION", latency_ms=1)
    snapshot = metrics.snapshot()
    read = next(item for item in snapshot["tools"] if item["tool_id"] == "read")
    bash = next(item for item in snapshot["tools"] if item["tool_id"] == "bash")
    assert read["total"] == 2
    assert read["success"] == 2
    assert read["avg_latency_ms"] == 20
    assert bash["total"] == 2
    assert bash["failure"] == 2
    assert bash["timeout"] == 1
    assert bash["last_error_code"] == "VALIDATION"
    assert snapshot["summary"]["total_calls"] == 4
    assert snapshot["summary"]["total_timeouts"] == 1


def test_metrics_circuit_trips_on_infrastructure_failures(monkeypatch) -> None:
    clock = _Clock(1000.0)
    monkeypatch.setattr(metrics_mod.time, "time", clock)
    metrics = ToolMetrics(failure_threshold=2, cooldown_s=30.0)
    metrics.record_call("t", "srv", ok=False, error_code="INTERNAL")
    metrics.record_call("t", "srv", ok=False, error_code="INTERNAL")
    assert metrics.is_open("srv") is True
    circuit = next(item for item in metrics.snapshot()["circuits"] if item["server_id"] == "srv")
    assert circuit["state"] == "open"
    assert circuit["consecutive_failures"] == 2
    assert circuit["opened_at"] == 1000.0


def test_metrics_business_errors_do_not_trip_circuit() -> None:
    metrics = ToolMetrics(failure_threshold=2, cooldown_s=30.0)
    for _ in range(5):
        metrics.record_call("t", "srv", ok=False, error_code="VALIDATION")
    assert metrics.is_open("srv") is False
    circuit = next(item for item in metrics.snapshot()["circuits"] if item["server_id"] == "srv")
    assert circuit["consecutive_failures"] == 0


def test_metrics_success_resets_consecutive_failures() -> None:
    metrics = ToolMetrics(failure_threshold=3, cooldown_s=30.0)
    metrics.record_call("t", "srv", ok=False, error_code="INTERNAL")
    metrics.record_call("t", "srv", ok=True)
    metrics.record_call("t", "srv", ok=False, error_code="INTERNAL")
    circuit = next(item for item in metrics.snapshot()["circuits"] if item["server_id"] == "srv")
    assert circuit["consecutive_failures"] == 1
    assert circuit["state"] == "closed"


def test_metrics_circuit_recovers_after_cooldown(monkeypatch) -> None:
    clock = _Clock(1000.0)
    monkeypatch.setattr(metrics_mod.time, "time", clock)
    metrics = ToolMetrics(failure_threshold=1, cooldown_s=30.0)
    metrics.record_call("t", "srv", ok=False, error_code="TIMEOUT")
    assert metrics.is_open("srv") is True
    clock.value = 1000.0 + 31.0  # 冷却期满
    assert metrics.is_open("srv") is False
    assert metrics.is_open("srv") is False  # 已恢复，幂等


def test_metrics_snapshot_and_reset() -> None:
    metrics = ToolMetrics()
    metrics.record_call("read", "platform.files", ok=True)
    snapshot = metrics.snapshot()
    assert set(snapshot) == {"tools", "circuits", "summary"}
    assert snapshot["summary"]["open_servers"] == []
    metrics.reset()
    assert metrics.snapshot()["summary"]["total_calls"] == 0


# —— MCPClientManager 熔断与度量 ——


def test_manager_fast_rejects_when_circuit_open() -> None:
    registry = _registry_with()
    metrics = ToolMetrics(failure_threshold=2, cooldown_s=60.0)
    manager = MCPClientManager.build_from_registry(registry, metrics=metrics)
    for _ in range(2):
        result = asyncio.run(manager.call_tool("platform.custom.boom", {}, _ctx()))
        assert result.ok is False
        assert result.error["code"] == "INTERNAL"
    # 服务器已熔断 → ok 工具也快速拒绝，不进入 handler
    result = asyncio.run(manager.call_tool("platform.custom.ok", {}, _ctx()))
    assert result.ok is False
    assert result.error["code"] == "VALIDATION"
    assert "熔断" in result.error["message"]
    snapshot = metrics.snapshot()
    ok_stat = next(item for item in snapshot["tools"] if item["tool_id"] == "platform.custom.ok")
    assert ok_stat["failure"] == 1
    assert ok_stat["last_error_code"] == "CIRCUIT_OPEN"


def test_manager_records_latency_and_error_codes() -> None:
    registry = _registry_with()
    metrics = ToolMetrics()
    manager = MCPClientManager.build_from_registry(registry, metrics=metrics)
    ok = asyncio.run(manager.call_tool("platform.custom.ok", {}, _ctx()))
    assert ok.ok is True
    boom = asyncio.run(manager.call_tool("platform.custom.boom", {}, _ctx()))
    assert boom.ok is False
    snapshot = metrics.snapshot()
    ok_stat = next(item for item in snapshot["tools"] if item["tool_id"] == "platform.custom.ok")
    boom_stat = next(item for item in snapshot["tools"] if item["tool_id"] == "platform.custom.boom")
    assert ok_stat["success"] == 1
    assert boom_stat["failure"] == 1
    assert boom_stat["last_error_code"] == "INTERNAL"
    # 熔断未触发（仅 1 次 INTERNAL 失败 < 默认阈值）
    assert metrics.is_open("platform.custom") is False


# —— 资源配额 + 审计 ——


def test_create_task_quota_rejected_with_audit(monkeypatch) -> None:
    """用户活动任务达上限 → CONCURRENCY + task_quota_rejected 审计。"""
    db = _FakeDb(session_row=_SessionRow(), task_query=[], task_count=5)
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    with pytest.raises(AppError) as error:
        create_task_safe(
            {"kind": "benchmark", "dataset_id": "d1", "profile_ids": ["p1"], "run": {}},
            _ctx(),
        )
    assert error.value.code == ErrorCode.CONCURRENCY
    assert "配额" in error.value.message
    assert any(
        isinstance(obj, AuditLog) and obj.action == "task_quota_rejected" for obj in db.added
    )
    assert db.commit_calls >= 1


def test_create_task_passes_quota_below_limit(monkeypatch) -> None:
    """资源合法且归属当前成员时，低于配额的任务可以入队。"""
    profile = ProtocolProfile(
        id="p1", name="测试评测档", protocol="openai_chat",
        base_url="https://model.example.test/v1", model="test-model", created_by="u1",
    )
    db = _FakeDb(session_row=_SessionRow(), task_query=[], task_count=2, profiles={"p1": profile})
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    result = create_task_safe(
        {"kind": "benchmark", "dataset_id": "d1", "profile_ids": ["p1"], "run": {}},
        _ctx(),
    )
    assert result["status"] == "queued"


def test_count_active_tasks_filters_by_user() -> None:
    db = _FakeDb(task_count=3)
    assert count_active_tasks(db, user_id="u1") == 3


def test_rest_create_task_quota_shared_rule() -> None:
    """REST POST /api/tasks 走同一配额规则（count_active_tasks + 审计）。"""
    from fastapi import Request

    from app.models import User
    from app.routers.tasks import create_task
    from app.schemas import RunConfig, TaskCreate

    db = _FakeDb(session_row=_SessionRow(), task_query=[], task_count=5)
    body = TaskCreate(
        kind="benchmark",
        dataset_id="d1",
        session_id="s1",
        profile_ids=["p1"],
        run=RunConfig(),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "headers": {},
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
    )
    user = User(id="u1", username="u1", password_hash="x")
    with pytest.raises(AppError) as error:
        create_task(body=body, request=request, db=db, user=user)
    assert error.value.code == ErrorCode.CONCURRENCY
    assert "配额" in error.value.message
    assert any(
        isinstance(obj, AuditLog) and obj.action == "task_quota_rejected" for obj in db.added
    )


# —— worker 取消传播 ——


def test_is_cancelled_detects_terminated_status() -> None:
    from worker.app.task_state import is_cancelled

    for status, expected in [("cancelled", True), ("failed", True), ("running", False), ("queued", False)]:
        db = _FakeDb(task_first=(status,))
        assert is_cancelled(db, "t1") is expected


def test_build_default_registry_includes_native_task_plan_and_mcp_task_bridge() -> None:
    registry = build_default_registry()
    assert len(registry.names()) == 18
    assert {"TaskCreate", "TaskGet", "TaskUpdate", "TaskList", "ask_user_question"} <= set(registry.names())
