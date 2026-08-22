"""跨模块运行时基础契约。

这里只放模型调用、编排和传输层都可能使用的轻量取消与追踪类型，
不依赖 Harness、数据库或具体业务模块。
"""

from .cancellation import DEFAULT_PROPAGATION_BUDGET_MS, CancellationToken, TurnCancelled
from .trace import (
    TraceContext,
    current_trace,
    format_trace_prefix,
    new_call_id,
    new_span_id,
    new_trace_id,
    new_turn_id,
    using_trace,
)

__all__ = [
    "DEFAULT_PROPAGATION_BUDGET_MS",
    "CancellationToken",
    "TraceContext",
    "TurnCancelled",
    "current_trace",
    "format_trace_prefix",
    "new_call_id",
    "new_span_id",
    "new_trace_id",
    "new_turn_id",
    "using_trace",
]
