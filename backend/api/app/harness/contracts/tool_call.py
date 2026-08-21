"""ToolCall / ExecutionOutcome / ToolResult 契约；模型 JSON 不得自带 trace。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from .errors import ErrorClass
from .trace import new_call_id


class OutcomeStatus(StrEnum):
    """执行层统一状态；禁止成功返回 dict、失败向上裸抛。"""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PENDING = "pending"
    CANCEL_REQUESTED = "cancel_requested"


class ToolCall(BaseModel):
    """经 Schema 校验后的可执行动作；trace 由编排层绑定。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(default_factory=new_call_id)
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    thought: str = ""
    done: bool = False
    reply: str = ""
    batch_index: int = 0
    trace_id: str | None = None
    span_id: str | None = None

    @field_validator("thought")
    @classmethod
    def _clip_thought(cls, value: str) -> str:
        return str(value or "")[:512]

    @field_validator("reply")
    @classmethod
    def _clip_reply(cls, value: str) -> str:
        return str(value or "")[:4000]

    @field_validator("arguments")
    @classmethod
    def _ensure_object(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("arguments 必须是 JSON object")
        return value


class ToolCallBatch(BaseModel):
    """一次结构化响应中的工具批次；并行需逐项满足 parallel_safe。"""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    thought: str = ""
    done: bool = False
    reply: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _assign_batch_index(self) -> ToolCallBatch:
        seen: set[str] = set()
        for index, call in enumerate(self.tool_calls):
            call.batch_index = index
            if call.call_id in seen:
                raise ValueError("call_id 必须在 Turn 内唯一")
            seen.add(call.call_id)
        return self


class ExecutionError(BaseModel):
    """执行失败的结构化错误；message 已脱敏，不得含密钥或堆栈。"""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    class_: ErrorClass = Field(alias="class")
    message: str
    retryable: bool = False
    diagnostic_id: str | None = None

    @model_serializer(mode="wrap")
    def _dump_error_class_alias(self, serializer: Any) -> dict[str, Any]:
        """JSON 键必须是 class，兼容未识别 serialize_by_alias 的 Pydantic 2.10。"""
        payload = serializer(self)
        if "class_" in payload and "class" not in payload:
            payload["class"] = payload.pop("class_")
        return payload


class ExecutionSource(BaseModel):
    """工具结果来源，供审计与 observation 标注。"""

    model_config = ConfigDict(extra="forbid")

    server: str = "local"
    transport: str = "inproc"


class ExecutionOutcome(BaseModel):
    """执行层唯一返回类型。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    trace_id: str
    span_id: str
    tool: str
    status: OutcomeStatus
    data: dict[str, Any] | list[Any] | None = None
    error: ExecutionError | None = None
    latency_ms: int = 0
    source: ExecutionSource = Field(default_factory=ExecutionSource)
    job_ref: str | None = None
    parent_span_id: str | None = None

    @classmethod
    def ok(
        cls,
        call: ToolCall,
        data: Any,
        *,
        trace_id: str,
        span_id: str,
        latency_ms: int,
        parent_span_id: str | None = None,
    ) -> ExecutionOutcome:
        payload = data if isinstance(data, dict | list) or data is None else {"value": data}
        return cls(
            call_id=call.call_id,
            trace_id=trace_id,
            span_id=span_id,
            tool=call.tool or "",
            status=OutcomeStatus.OK,
            data=payload,
            latency_ms=latency_ms,
            parent_span_id=parent_span_id,
        )

    @classmethod
    def failed(
        cls,
        call: ToolCall,
        error_class: ErrorClass,
        message: str,
        *,
        trace_id: str,
        span_id: str,
        status: OutcomeStatus = OutcomeStatus.ERROR,
        retryable: bool = False,
        diagnostic_id: str | None = None,
        latency_ms: int = 0,
        parent_span_id: str | None = None,
    ) -> ExecutionOutcome:
        return cls(
            call_id=call.call_id,
            trace_id=trace_id,
            span_id=span_id,
            tool=call.tool or "",
            status=status,
            error=ExecutionError(
                class_=error_class,
                message=message,
                retryable=retryable,
                diagnostic_id=diagnostic_id,
            ),
            latency_ms=latency_ms,
            parent_span_id=parent_span_id,
        )

    @classmethod
    def cancelled(
        cls,
        call: ToolCall,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        requested: bool = False,
    ) -> ExecutionOutcome:
        status = OutcomeStatus.CANCEL_REQUESTED if requested else OutcomeStatus.CANCELLED
        return cls.failed(
            call,
            ErrorClass.CANCELLED,
            "调用已取消",
            trace_id=trace_id,
            span_id=span_id,
            status=status,
            parent_span_id=parent_span_id,
        )


class ToolResult(BaseModel):
    """脱敏后可注入下一轮上下文的 observation。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    batch_index: int = 0
    tool: str
    status: OutcomeStatus
    ok: bool
    data: Any = None
    error: str | None = None
    error_class: ErrorClass | None = None
    latency_ms: int = 0
    source_id: str | None = None
    trace_id: str
    span_id: str
    caused_by_span_id: str | None = None
    diagnostic_id: str | None = None
    truncated: bool = False


class ToolResultBatch(BaseModel):
    """批次反馈：按 batch_index 顺序阅读，按 call_id 精确关联。"""

    model_config = ConfigDict(extra="forbid")

    ordered_results: list[ToolResult]
    results_by_call_id: dict[str, ToolResult]

    @classmethod
    def from_results(cls, results: list[ToolResult]) -> ToolResultBatch:
        ordered = sorted(results, key=lambda item: item.batch_index)
        return cls(
            ordered_results=ordered,
            results_by_call_id={item.call_id: item for item in ordered},
        )
