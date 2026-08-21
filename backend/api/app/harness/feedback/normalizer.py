"""Outcome → 脱敏 ToolResult。

普通工具失败必须收敛为 ToolResult；缺 trace / 父子不匹配则 Fail-fast，
不得降级成可回填模型的工具错误。批量 merge_batch 归属阶段 3，本阶段不公开。
"""

from __future__ import annotations

from app.harness.contracts.errors import MissingTraceContext, TraceMismatch
from app.harness.contracts.tool_call import ExecutionOutcome, OutcomeStatus, ToolResult
from app.harness.contracts.trace import TraceContext
from app.harness.feedback.redaction import truncate_tool_data


def _blank(value: str | None) -> bool:
    """空串或纯空白视为缺 trace。"""
    return not str(value or "").strip()


def normalize(outcome: ExecutionOutcome, *, trace: TraceContext, batch_index: int = 0) -> ToolResult:
    """单调用路径的父子校验：Feedback span 的 parent 必须等于执行 span。"""
    if _blank(outcome.trace_id) or _blank(outcome.span_id):
        raise MissingTraceContext("Feedback 拒绝未携带 trace_id/span_id 的 Outcome")
    if outcome.trace_id != trace.trace_id:
        raise TraceMismatch("Feedback 拒绝不具备同一 trace_id 的合并")
    if trace.parent_span_id and trace.parent_span_id != outcome.span_id:
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
