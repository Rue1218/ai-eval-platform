"""阶段 2：强制 trace/cancel、本地取消调度与审计表。"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.agent.defaults import HARD_MAX_TOOL_ROUNDS, TURN_WALL_CLOCK_S
from app.harness.contracts.cancellation import (
    DEFAULT_PROPAGATION_BUDGET_MS,
    CancellationToken,
)
from app.harness.contracts.errors import MissingTraceContext
from app.harness.contracts.tool_call import OutcomeStatus, ToolCall
from app.harness.contracts.trace import TraceContext, using_trace
from app.harness.contracts.turn import TurnStatus
from app.harness.execution.facade import execute
from app.harness.feedback.diagnostics import record_diagnostic, reset_audit_store
from app.harness.feedback.publisher import InMemoryPublisher, reset_publisher
from app.harness.llm.client import stream_agent_model
from app.harness.orchestration.budgets import (
    max_react_steps,
    same_call_fingerprint_cap,
    turn_deadline_s,
)
from app.harness.orchestration.react_adapter import run_react
from app.harness.orchestration.react_loop import emit_and_run_tool, run_react_loop, stream_mcp_step
from app.harness.orchestration.session_runtime import (
    SessionHarness,
    abort_running_turn,
    session_harness,
)
from app.models import Base


class _Db:
    def close(self) -> None:
        return None


def test_execute_and_react_loop_require_trace_and_cancel():
    """公开执行/编排/LLM 流 API 缺少 trace/cancel 不得带默认值。"""
    for fn in (
        execute,
        run_react_loop,
        emit_and_run_tool,
        run_react,
        stream_mcp_step,
        stream_agent_model,
    ):
        params = inspect.signature(fn).parameters
        assert params["trace"].default is inspect.Parameter.empty, fn.__name__
        assert params["cancel"].default is inspect.Parameter.empty, fn.__name__


def test_execute_omitting_trace_raises_type_error():
    """省略 trace 的调用在单测中失败。"""
    call = ToolCall(tool="image.generate", arguments={})
    with pytest.raises(TypeError):
        asyncio.run(execute(call, db=_Db(), user_id="u1", cancel=CancellationToken(turn_id="t")))


def test_execute_already_cancelled_returns_cancelled_outcome():
    """取消发生在工具开始前：本地未启动，记 cancelled 而非 cancel_requested。"""
    cancel = CancellationToken(turn_id="turn-1")
    cancel.request("user_stop")
    span = TraceContext.for_turn(component="execution.facade")
    call = ToolCall(
        tool="image.generate",
        arguments={"prompt": "x"},
        trace_id=span.trace_id,
        span_id=span.span_id,
    )
    outcome = asyncio.run(execute(call, trace=span, db=_Db(), user_id="u1", cancel=cancel))
    assert outcome.status is OutcomeStatus.CANCELLED
    assert outcome.error is not None
    assert outcome.error.message == "调用已取消"


def test_abort_running_turn_dispatches_within_100ms():
    """/stop 等价路径：request + task.cancel 的本地调度低于 100ms。"""

    async def _body() -> None:
        trace = TraceContext.for_turn(component="dispatch")
        cancel = CancellationToken(turn_id=trace.turn_id)
        task = asyncio.create_task(asyncio.sleep(30))
        handle = SessionHarness(
            user_id="u1",
            abort=asyncio.Event(),
            stop=cancel.stop,
            cancel=cancel,
            trace=trace,
            task=task,
        )
        from app.harness.orchestration import session_runtime as harness_mod

        harness_mod._HARNESS_BY_SESSION["sess-stop"] = handle
        store = reset_publisher(store=InMemoryPublisher())
        store.start_turn(trace, session_id="sess-stop")
        try:
            assert abort_running_turn("sess-stop", reason="user_stop", user_id="u1") is True
            assert cancel.reason == "user_stop"
            assert cancel.stop.is_set()
            assert handle.abort.is_set()
            latency = cancel.dispatch_latency_ms()
            assert latency is not None
            assert latency < DEFAULT_PROPAGATION_BUDGET_MS
            assert session_harness("sess-stop") is handle
            assert store.turns[0]["status"] == TurnStatus.CANCELLING
            store.finish_turn(trace, status=TurnStatus.CANCELLED)
            assert store.turns[0]["status"] == TurnStatus.CANCELLED
            assert any("CANCELLING" in line for line in store.logs)
        finally:
            reset_publisher()
            task.cancel()
            harness_mod._HARNESS_BY_SESSION.pop("sess-stop", None)
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(_body())


def test_budget_defaults_remain_product_values(monkeypatch):
    """未设 env 时硬顶 5、墙钟 180s，指纹类截断默认关。"""
    for key in (
        "HARNESS_MAX_REACT_STEPS",
        "HARNESS_TURN_DEADLINE_S",
        "HARNESS_MAX_SAME_CALL_FINGERPRINT",
        "HARNESS_MAX_CONSECUTIVE_RETRYABLE_ERROR",
        "HARNESS_MAX_CONTEXT_REBUILDS",
    ):
        monkeypatch.delenv(key, raising=False)
    assert max_react_steps() == HARD_MAX_TOOL_ROUNDS == 5
    assert turn_deadline_s() == float(TURN_WALL_CLOCK_S) == 180.0
    assert same_call_fingerprint_cap() is None


def test_publisher_logs_include_trace_id_and_reject_blank():
    """publisher 日志自动带 trace_id；缺 trace 仍 Fail-fast。"""
    store = reset_publisher(store=InMemoryPublisher())
    trace = TraceContext.for_turn(component="orchestration.react")
    store.start_turn(trace, session_id="abcd1234-session")
    store.record_span(trace.child("execution.facade"), latency_ms=3)
    store.finish_turn(trace, status=TurnStatus.FINISHED)
    assert store.turns[0]["trace_id"] == trace.trace_id
    assert store.spans[0]["component"] == "execution.facade"
    assert any(trace.trace_id in line and "turn_id=" in line for line in store.logs)
    reset_audit_store()
    with pytest.raises(MissingTraceContext):
        record_diagnostic(RuntimeError("boom"), trace=SimpleNamespace(trace_id="", span_id="S-1"))  # type: ignore[arg-type]
    reset_publisher()


def test_agent_trace_auto_includes_bound_trace_ids(capsys):
    """绑定 TraceContext 后，热路径 agent_trace 自动带 trace_id/span_id/turn_id。"""
    from app.agent.log import agent_trace

    trace = TraceContext.for_turn(component="orchestration.react")
    with using_trace(trace):
        agent_trace("ReAct 决策不可用")
    captured = capsys.readouterr().err
    assert f"trace_id={trace.trace_id}" in captured
    assert f"span_id={trace.span_id}" in captured
    assert f"turn_id={trace.turn_id}" in captured


def test_audit_tables_are_on_shared_metadata():
    """三张审计表注册在 PostgreSQL 元数据，不进 Redis。"""
    tables = set(Base.metadata.tables)
    assert {"harness_turns", "harness_spans", "harness_diagnostics"} <= tables
    assert "redis" not in tables


def test_mcp_cancelled_notification_not_implemented():
    """无 MCP 客户端时不得伪报已向 Server 发取消。"""
    from pathlib import Path

    client = Path(__file__).resolve().parents[2] / "app" / "harness" / "execution" / "mcp" / "client.py"
    text = client.read_text(encoding="utf-8")
    assert "CancelledNotification" not in text
