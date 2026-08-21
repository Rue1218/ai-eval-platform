"""记忆层 Port：Context 只依赖本协议，禁止 import 任何存储 SDK。"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .trace import TraceContext


class MemoryQuery(BaseModel):
    """记忆检索请求；必须携带租户/会话/权限范围。"""

    model_config = ConfigDict(extra="forbid")

    query_text: str
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    permitted_resource_ids: list[str] = Field(default_factory=list)
    intent: str = ""
    record_types: list[str] = Field(default_factory=lambda: ["conversation", "knowledge"])
    time_range: tuple[str, str] | None = None
    top_k_recall: int = 20
    trace_id: str

    @field_validator("trace_id")
    @classmethod
    def _require_trace_id(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("MemoryQuery.trace_id 不可为空")
        return value


class MemoryRecord(BaseModel):
    """候选记忆；缺少 source_id 的文本不得作为高可信事实。"""

    model_config = ConfigDict(extra="forbid")

    record_id: str
    source_id: str
    version: int = 1
    text: str
    record_type: str = "conversation"
    timestamp: str = ""
    score: float = 0.0
    acl: str = "session"
    origin_trace_id: str | None = None
    origin_span_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryPort(Protocol):
    """短期 + 长期记忆的统一端口。"""

    async def retrieve(
        self,
        query: MemoryQuery,
        *,
        trace: TraceContext,
    ) -> list[MemoryRecord]:
        """在 ACL 过滤之后返回候选记录。"""
        ...

    async def append(
        self,
        record: MemoryRecord,
        *,
        trace: TraceContext,
    ) -> None:
        """写入一条可溯源记录。"""
        ...

    async def forget(
        self,
        source_id: str,
        *,
        trace: TraceContext,
    ) -> None:
        """撤权或删除后，相关摘要必须失效。"""
        ...
