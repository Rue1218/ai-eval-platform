"""Outcome → 脱敏 ToolResult。

普通工具失败必须收敛为 ToolResult；缺 trace / 父子不匹配则 Fail-fast，
不得降级成可回填模型的工具错误。批量路径额外校验批次执行 span。
"""

from __future__ import annotations

from app.harness.contracts.errors import MissingTraceContext, TraceMismatch
from app.harness.contracts.tool_call import (
    ExecutionOutcome,
    OutcomeStatus,
    ToolCallBatch,
    ToolResult,
    ToolResultBatch,
)
from app.harness.contracts.trace import TraceContext
from app.harness.feedback.redaction import truncate_tool_data


def _blank(value: str | None) -> bool:
    """空串或纯空白视为缺 trace。"""
    return not str(value or "").strip()


def normalize(
    outcome: ExecutionOutcome,
    *,
    trace: TraceContext,
    batch_index: int = 0,
    batch_execution_span: TraceContext | None = None,
) -> ToolResult:
    """单调用校验 Feedback 父子；批量校验 Outcome 是批次执行 span 的直属子项。"""
    if _blank(outcome.trace_id) or _blank(outcome.span_id):
        raise MissingTraceContext("Feedback 拒绝未携带 trace_id/span_id 的 Outcome")
    if outcome.trace_id != trace.trace_id:
        raise TraceMismatch("Feedback 拒绝不具备同一 trace_id 的合并")
    if batch_execution_span is not None:
        if batch_execution_span.trace_id != outcome.trace_id:
            raise TraceMismatch("Feedback 拒绝跨 trace 的批次合并")
        if outcome.parent_span_id != batch_execution_span.span_id:
            raise TraceMismatch("Feedback 拒绝不属于批次执行 span 的 Outcome")
    elif trace.parent_span_id and trace.parent_span_id != outcome.span_id:
        raise TraceMismatch("Feedback 拒绝不具备父子关系的 trace/span 合并")
    ok = outcome.status is OutcomeStatus.OK
    error_message = outcome.error.message if outcome.error else None
    data = truncate_tool_data(outcome.data) if ok else None
    truncated = isinstance(data, dict) and bool(data.get("truncated"))
    return ToolResult(
        call_id=outcome.call_id,
        batch_index=batch_index,
        tool=outcome.tool,
        status=outcome.status,
        ok=ok,
        data=data,
        error=error_message,
        error_class=outcome.error.class_ if outcome.error else None,
        latency_ms=outcome.latency_ms,
        source_id=f"tool:{outcome.tool}",
        trace_id=trace.trace_id,
        span_id=trace.span_id,
        caused_by_span_id=outcome.span_id,
        diagnostic_id=outcome.error.diagnostic_id if outcome.error else None,
        truncated=truncated,
    )


def merge_batch(
    batch: ToolCallBatch,
    outcomes: list[ExecutionOutcome],
    *,
    batch_execution_span: TraceContext,
    trace: TraceContext,
) -> ToolResultBatch:
    """按 call_id 逐项归并批次结果；任一 trace/span 异常均熔断整 Turn。"""
    calls_by_id = {call.call_id: call for call in batch.tool_calls}
    if len(calls_by_id) != len(batch.tool_calls) or len(outcomes) != len(batch.tool_calls):
        raise TraceMismatch("Feedback 拒绝长度或 call_id 不一致的批次合并")

    seen: set[str] = set()
    results: list[ToolResult] = []
    for outcome in outcomes:
        call = calls_by_id.get(outcome.call_id)
        if call is None or outcome.call_id in seen:
            raise TraceMismatch("Feedback 拒绝无法与批次 call_id 一一对应的 Outcome")
        seen.add(outcome.call_id)
        results.append(
            normalize(
                outcome,
                trace=trace,
                batch_index=call.batch_index,
                batch_execution_span=batch_execution_span,
            )
        )
    return ToolResultBatch.from_results(results)
