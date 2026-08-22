"""短期与长期记忆的组合端口；Context 只能依赖此处导出的实现。"""

from dataclasses import dataclass, field

from app.errors import AppError, ErrorCode
from app.harness.contracts.memory import (
    MemoryPort,
    MemoryQuery,
    MemoryRecord,
    validate_memory_query,
)
from app.harness.contracts.trace import TraceContext


def is_record_visible(record: MemoryRecord, query: MemoryQuery) -> bool:
    """在 Port 边界执行最小 ACL 与撤权过滤，不能把不可信记录交给 Context。"""
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    if metadata.get("forgotten") is True:
        return False
    for key, expected in (
        ("tenant_id", query.tenant_id),
        ("user_id", query.user_id),
        ("session_id", query.session_id),
    ):
        actual = metadata.get(key)
        if actual not in (None, "", expected):
            return False
    allowed_users = metadata.get("allowed_user_ids")
    if isinstance(allowed_users, list) and allowed_users and query.user_id not in allowed_users:
        return False
    # 知识记录必须声明可访问来源，避免缺 ACL 的内容被当作通用事实。
    if record.record_type == "knowledge":
        return bool(query.permitted_resource_ids) and record.source_id in query.permitted_resource_ids
    return True


@dataclass
class InMemoryMemoryPort(MemoryPort):
    """单测与本地开发使用的内存 Port，不连接 Redis 或 PostgreSQL。"""

    records: list[MemoryRecord] = field(default_factory=list)
    forgotten_source_ids: set[str] = field(default_factory=set)

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """按归属、ACL 与撤权状态返回稳定排序的候选记录。"""
        validate_memory_query(query, trace)
        candidates = [
            record
            for record in self.records
            if record.source_id not in self.forgotten_source_ids
            and record.record_type in query.record_types
            and is_record_visible(record, query)
        ]
        return sorted(candidates, key=lambda item: (-item.score, item.record_id))[: query.top_k_recall]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """追加带 trace 来源的记录；相同 record_id 覆盖以保证调用幂等。"""
        if not record.source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "记忆记录缺少来源")
        normalized = record.model_copy(
            update={
                "origin_trace_id": record.origin_trace_id or trace.trace_id,
                "origin_span_id": record.origin_span_id or trace.span_id,
            }
        )
        self.records = [item for item in self.records if item.record_id != normalized.record_id]
        self.records.append(normalized)

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """撤权后立即从后续召回中移除同一来源的全部记录。"""
        if not source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "记忆来源不可为空")
        self.forgotten_source_ids.add(source_id)
        self.records = [item for item in self.records if item.source_id != source_id]


@dataclass
class CompositeMemoryPort(MemoryPort):
    """组合短期、对话归档与知识库实现，统一去重并保持 Port 语义。"""

    short_term: MemoryPort | None = None
    conversation: MemoryPort | None = None
    knowledge: MemoryPort | None = None

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """先由各存储各自 ACL 过滤，再按首次出现顺序去重合并。

        会话时间序（ConversationStore）与知识相关度序（pgvector Store）都由各
        存储在各自检索内给出；本层禁止再按 score/record_id 全局重排——record_id
        是随机 UUID，字典序决序会把会话历史打乱。同一 record_id 保留最高分版本。
        """
        validate_memory_query(query, trace)
        merged: list[MemoryRecord] = []
        first_seen_index: dict[str, int] = {}
        for store in (self.short_term, self.conversation, self.knowledge):
            if store is None:
                continue
            for record in await store.retrieve(query, trace=trace):
                seen = first_seen_index.get(record.record_id)
                if seen is None:
                    first_seen_index[record.record_id] = len(merged)
                    merged.append(record)
                elif record.score > merged[seen].score:
                    merged[seen] = record
        return merged[: query.top_k_recall]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """短期必写；长期按记录类型分派，失败不吞掉以免伪造成功。"""
        if self.short_term is not None:
            await self.short_term.append(record, trace=trace)
        target = self.knowledge if record.record_type == "knowledge" else self.conversation
        if target is not None:
            await target.append(record, trace=trace)

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """向全部存储传播撤权，任一失败都阻止上层继续当作已遗忘。"""
        for store in (self.short_term, self.conversation, self.knowledge):
            if store is not None:
                await store.forget(source_id, trace=trace)
