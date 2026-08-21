"""跨层唯一数据契约：无 I/O、无 LLM SDK。"""

from .cancellation import CancellationToken
from .context import CompiledContext, ContextItem, Provenance, TokenLedger
from .errors import (
    DiagnosticRef,
    ErrorClass,
    MissingTraceContext,
    RetryPolicy,
    TraceMismatch,
    map_error_class_to_code,
)
from .memory import MemoryPort, MemoryQuery, MemoryRecord
from .tool_call import (
    ExecutionError,
    ExecutionOutcome,
    ExecutionSource,
    OutcomeStatus,
    ToolCall,
    ToolCallBatch,
    ToolResult,
    ToolResultBatch,
)
from .trace import TraceContext, new_span_id, new_trace_id, new_turn_id

__all__ = [
    "CancellationToken",
    "CompiledContext",
    "ContextItem",
    "DiagnosticRef",
    "ErrorClass",
    "ExecutionError",
    "ExecutionOutcome",
    "ExecutionSource",
    "MemoryPort",
    "MemoryQuery",
    "MemoryRecord",
    "MissingTraceContext",
    "OutcomeStatus",
    "Provenance",
    "RetryPolicy",
    "TokenLedger",
    "ToolCall",
    "ToolCallBatch",
    "ToolResult",
    "ToolResultBatch",
    "TraceContext",
    "TraceMismatch",
    "map_error_class_to_code",
    "new_span_id",
    "new_trace_id",
    "new_turn_id",
]
