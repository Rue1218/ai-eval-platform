"""跨层 TraceContext / CancellationToken / Feedback normalize 的 fail-fast 单测。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.harness.contracts.cancellation import (
    DEFAULT_PROPAGATION_BUDGET_MS,
    CancellationToken,
    TurnCancelled,
)
from app.harness.contracts.errors import ErrorClass, MissingTraceContext, TraceMismatch
from app.harness.contracts.tool_call import (
    ExecutionError,
    ExecutionOutcome,
    OutcomeStatus,
    ToolCall,
)
from app.harness.contracts.trace import TraceContext
from app.harness.feedback.diagnostics import (
    InMemoryAuditStore,
    audit_store,
    record_diagnostic,
    reset_audit_store,
)
from app.harness.feedback.normalizer import normalize


def test_child_span_keeps_same_trace_id():
    """子 span 必须同 trace_id、新 span_id，并把当前 span 记为 parent。"""
    root = TraceContext.for_turn(turn_id="turn-test")
    child = root.child("context.compile")
    assert child.trace_id == root.trace_id
    assert child.turn_id == root.turn_id
    assert child.span_id != root.span_id
    assert child.parent_span_id == root.span_id
    assert child.component == "context.compile"


def test_trace_context_rejects_empty_ids():
    """trace_id / span_id / turn_id 为空直接拒绝构造。"""
    with pytest.raises(ValueError):
        TraceContext(trace_id="", span_id="S-1", turn_id="turn-1")
    with pytest.raises(ValueError):
        TraceContext(trace_id="T-1", span_id="", turn_id="turn-1")
    with pytest.raises(ValueError):
        TraceContext(trace_id="T-1", span_id="S-1", turn_id="")


def test_normalize_rejects_missing_trace_on_outcome():
    """缺 trace 的 Outcome 不是普通工具错误，Feedback 必须 Fail-fast。"""
    call = ToolCall(call_id="call-1", tool="image.generate", arguments={})
    outcome = ExecutionOutcome(
        call_id=call.call_id,
        trace_id="",
        span_id="",
        tool="image.generate",
        status=OutcomeStatus.OK,
        data={"ok": True},
    )
    feedback = TraceContext.for_turn()
    with pytest.raises(MissingTraceContext):
        normalize(outcome, trace=feedback)
    blank = ExecutionOutcome(
        call_id=call.call_id,
        trace_id="   ",
        span_id="S-1",
        tool="image.generate",
        status=OutcomeStatus.OK,
        data={"ok": True},
    )
    with pytest.raises(MissingTraceContext):
        normalize(blank, trace=feedback)


def test_normalize_rejects_trace_id_mismatch():
    """Feedback 拒绝把不同 Turn 的 Outcome 合并进当前 trace。"""
    exec_trace = TraceContext.for_turn()
    call = ToolCall(call_id="call-1", tool="image.generate", arguments={})
    outcome = ExecutionOutcome.ok(
        call,
        {"file_id": "f1"},
        trace_id=exec_trace.trace_id,
        span_id=exec_trace.span_id,
        latency_ms=10,
    )
    other = TraceContext.for_turn()
    with pytest.raises(TraceMismatch):
        normalize(outcome, trace=other)


def test_normalize_rejects_parent_span_mismatch():
    """Feedback span 的 parent 必须等于执行 span，否则熔断。"""
    root = TraceContext.for_turn()
    exec_span = root.child("execution.call_01")
    wrong_feedback = root.child("feedback.normalize")
    call = ToolCall(call_id="call-1", tool="image.generate", arguments={})
    outcome = ExecutionOutcome.ok(
        call,
        {"file_id": "f1"},
        trace_id=exec_span.trace_id,
        span_id=exec_span.span_id,
        latency_ms=8,
    )
    with pytest.raises(TraceMismatch):
        normalize(outcome, trace=wrong_feedback)


def test_normalize_accepts_parent_child_span():
    """单调用路径：Feedback span 的 parent 必须等于执行 span。"""
    exec_trace = TraceContext.for_turn(component="execution.call_01")
    feedback = exec_trace.child("feedback.normalize")
    assert feedback.parent_span_id == exec_trace.span_id
    call = ToolCall(call_id="call-1", tool="image.generate", arguments={})
    outcome = ExecutionOutcome.ok(
        call,
        {"file_id": "f1", "api_key": "sk-live"},
        trace_id=exec_trace.trace_id,
        span_id=exec_trace.span_id,
        latency_ms=12,
        parent_span_id=exec_trace.parent_span_id,
    )
    result = normalize(outcome, trace=feedback)
    assert result.ok is True
    assert result.caused_by_span_id == exec_trace.span_id
    assert result.trace_id == exec_trace.trace_id
    assert result.data["file_id"] == "f1"
    assert result.data["api_key"] == "***"


def test_cancellation_token_default_budget_is_100ms():
    """取消传播调度 SLO 默认 100ms。"""
    token = CancellationToken(turn_id="turn-1")
    assert token.propagation_budget_ms == DEFAULT_PROPAGATION_BUDGET_MS == 100
    assert token.is_cancelled() is False


def test_cancellation_request_is_idempotent():
    """重复 request 保持首次 reason；raise_if_cancelled 必须退出。"""
    token = CancellationToken(turn_id="turn-1")
    token.request("user_stop")
    first_ts = token.requested_at_monotonic
    token.request("disconnect")
    assert token.reason == "user_stop"
    assert token.requested_at_monotonic == first_ts
    with pytest.raises(TurnCancelled):
        token.raise_if_cancelled()


def test_diagnostics_persist_exception_and_cap_store():
    """诊断必须写入传入异常，而不是 except 之外的空 format_exc。"""
    reset_audit_store(store=InMemoryAuditStore(max_items=3))
    trace = TraceContext.for_turn()
    for index in range(5):
        record_diagnostic(RuntimeError(f"boom-{index}"), trace=trace)
    items = audit_store().items
    assert len(items) == 3
    last = items[-1]["traceback"]
    assert "RuntimeError" in last
    assert "boom-4" in last
    assert items[0]["traceback"].count("boom-2") == 1
    reset_audit_store()
    assert audit_store().items == []


def test_execution_error_dumps_class_alias():
    """跨层 JSON 必须使用 error.class，不得泄漏 Python 字段名 class_。"""
    error = ExecutionError(class_=ErrorClass.MISSING_TOOL, message="未知工具")
    dumped = error.model_dump()
    assert dumped["class"] == "MISSING_TOOL"
    assert "class_" not in dumped
    call = ToolCall(call_id="call-1", tool="missing", arguments={})
    outcome = ExecutionOutcome.failed(
        call,
        ErrorClass.MISSING_TOOL,
        "未知工具",
        trace_id="T-1",
        span_id="S-1",
    )
    nested = outcome.model_dump()
    assert nested["error"]["class"] == "MISSING_TOOL"
    assert "class_" not in nested["error"]


def test_merge_batch_is_not_exported_in_phase_0():
    """批量 span 树归阶段 3；阶段 0 不得公开会绕过 Fail-fast 的 merge_batch。"""
    import app.harness.feedback as feedback
    import app.harness.feedback.normalizer as normalizer

    assert not hasattr(feedback, "merge_batch")
    assert not hasattr(normalizer, "merge_batch")


def test_tool_call_rejects_non_object_arguments():
    """arguments 必须是 JSON object，不能静默改成空 dict。"""
    with pytest.raises(ValidationError):
        ToolCall(tool="image.generate", arguments=["not-an-object"])
    with pytest.raises(ValidationError):
        ToolCall.model_validate({"tool": "image.generate", "foo": 1})


def test_tool_call_clips_thought_and_omits_trace_from_model_json():
    """thought 截断到 512；模型 JSON 不必也不该自带 trace。"""
    call = ToolCall(thought="a" * 600, arguments={"task_id": "t1"})
    dumped = call.model_dump()
    assert len(call.thought) == 512
    assert dumped["trace_id"] is None
    assert dumped["span_id"] is None
    assert dumped["arguments"] == {"task_id": "t1"}
