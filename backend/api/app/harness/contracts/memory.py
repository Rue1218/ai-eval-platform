"""记忆层 Port：Context 只依赖本协议，禁止 import 任何存储 SDK。"""

from __future__ import annotations

import math
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.errors import AppError, ErrorCode

from .trace import TraceContext


def _validate_embedding(value: list[float] | None) -> list[float] | None:
    """拒绝空、非有限或超长向量，避免把异常输入传递给 pgvector。"""
    if value is None:
        return None
    if not value or len(value) > 16_000:
        raise ValueError("记忆向量维度无效")
    if any(not math.isfinite(item) for item in value):
        raise ValueError("记忆向量必须是有限数值")
    return value


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
    # 向量由编排或 Embedding 适配器生成；Context 本身禁止调用模型。
    query_embedding: list[float] | None = None
    trace_id: str

    @field_validator("trace_id")
    @classmethod
    def _require_trace_id(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("MemoryQuery.trace_id 不可为空")
        return value

    @field_validator("query_embedding")
    @classmethod
    def _require_valid_query_embedding(cls, value: list[float] | None) -> list[float] | None:
        """仅允许有限的查询向量进入长期知识检索。"""
        return _validate_embedding(value)


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
    # 仅知识记录使用；对话归档仍以 messages 表为唯一正文来源。
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("embedding")
    @classmethod
    def _require_valid_record_embedding(cls, value: list[float] | None) -> list[float] | None:
        """写入 pgvector 前统一收紧记录向量格式。"""
        return _validate_embedding(value)


def validate_memory_query(query: MemoryQuery, trace: TraceContext) -> None:
    """收紧阶段 0 类型债务，拒绝无归属召回与跨 trace 的 Port 调用。"""
    missing = [
        name
        for name in ("tenant_id", "user_id", "session_id")
        if not str(getattr(query, name) or "").strip()
    ]
    if missing:
        raise AppError(ErrorCode.VALIDATION, "记忆检索缺少归属信息")
    if query.trace_id != trace.trace_id:
        raise AppError(ErrorCode.INTERNAL, "操作失败")


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
