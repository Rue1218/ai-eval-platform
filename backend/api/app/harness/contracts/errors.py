"""Harness 内部 observation 级错误枚举；不构成第二套对外 ErrorCode。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.errors import ErrorCode


class MissingTraceContext(Exception):
    """Outcome / 诊断缺少 trace_id 或 span_id：运行时不变量失败，熔断当前 Turn。"""


class TraceMismatch(Exception):
    """trace/span 父子关系不成立：批量合并或 Feedback 校验失败，熔断当前 Turn。"""


class ErrorClass(StrEnum):
    """回填模型的内部错误分类；对外 REST/WS 仍映射 10 大 ErrorCode。"""

    DONE_TOOL_CONFLICT = "DONE_TOOL_CONFLICT"
    MISSING_TOOL = "MISSING_TOOL"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    ARGUMENT_VALIDATION_ERROR = "ARGUMENT_VALIDATION_ERROR"
    PARALLEL_POLICY_VIOLATION = "PARALLEL_POLICY_VIOLATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NEED_APPROVAL = "NEED_APPROVAL"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    MCP_PROTOCOL_ERROR = "MCP_PROTOCOL_ERROR"
    TOOL_INTERNAL_ERROR = "TOOL_INTERNAL_ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class DiagnosticRef:
    """受限审计存储的引用；原始 traceback 不进入模型上下文。"""

    diagnostic_id: str
    trace_id: str
    span_id: str


@dataclass(frozen=True)
class RetryPolicy:
    """工具级重试策略；仅对标记 retryable 的错误生效。"""

    retryable: bool = False
    max_attempts: int = 1
    backoff_ms: int = 0


def map_error_class_to_code(error_class: ErrorClass, *, deadline: bool = False) -> ErrorCode | None:
    """内部枚举到对外 ErrorCode 的映射；返回 None 表示不对外、只作 observation。"""
    if error_class is ErrorClass.BUDGET_EXHAUSTED:
        return ErrorCode.TIMEOUT if deadline else ErrorCode.VALIDATION
    if error_class is ErrorClass.NEED_APPROVAL:
        return ErrorCode.NEED_APPROVAL
    if error_class is ErrorClass.UPSTREAM_TIMEOUT:
        return ErrorCode.TIMEOUT
    if error_class is ErrorClass.UPSTREAM_ERROR:
        return ErrorCode.UPSTREAM
    # 其余 observation 枚举（含 CANCELLED、解析冲突等）不构成对外 ErrorCode。
    return None
