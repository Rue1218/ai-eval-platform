"""短期与长期记忆的组合端口；Context 只能依赖本模块的 MemoryPort 实现。"""

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
    """在 Port 边界执行最小 ACL 与撤权过滤，缺归属的对话记录必须拒绝。"""
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    if metadata.get("forgotten") is True:
        return False
    if record.record_type == "conversation":
        # 会话消息不得缺任一归属字段，否则会被错误地当成全局可见历史。
        return all(
            str(metadata.get(key) or "").strip() == expected
            for key, expected in (
                ("tenant_id", query.tenant_id),
                ("user_id", query.user_id),
                ("session_id", query.session_id),
            )
        )
    if record.record_type == "knowledge":
        if str(metadata.get("tenant_id") or "").strip() != query.tenant_id:
            return False
        for key, expected in (("user_id", query.user_id), ("session_id", query.session_id)):
            actual = str(metadata.get(key) or "").strip()
            if actual and actual != expected:
                return False
        allowed_users = metadata.get("allowed_user_ids")
        if isinstance(allowed_users, list) and allowed_users and query.user_id not in allowed_users:
            return False
        return bool(query.permitted_resource_ids) and record.source_id in query.permitted_resource_ids
    # 未知记录类型没有明确 ACL 语义，必须按拒绝处理。
    return False


def _validate_append_scope(record: MemoryRecord) -> None:
    """在写入端拒绝无归属记录，避免脏数据绕过后续 retrieve 的 ACL。"""
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    if record.record_type == "conversation":
        required = ("tenant_id", "user_id", "session_id")
    elif record.record_type == "knowledge":
        # 知识可以跨会话复用，但仍必须隶属租户。
        required = ("tenant_id",)
    else:
        raise AppError(ErrorCode.VALIDATION, "记忆记录类型不受支持")
    if any(not str(metadata.get(key) or "").strip() for key in required):
        raise AppError(ErrorCode.VALIDATION, "记忆记录缺少归属信息")


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
        _validate_append_scope(record)
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
        """各存储先过滤，再按分数与记录 ID 稳定合并。"""
        validate_memory_query(query, trace)
        candidates: list[MemoryRecord] = []
        for store in (self.short_term, self.conversation, self.knowledge):
            if store is not None:
                candidates.extend(await store.retrieve(query, trace=trace))
        deduplicated: dict[str, MemoryRecord] = {}
        for record in candidates:
            current = deduplicated.get(record.record_id)
            if current is None or record.score > current.score:
                deduplicated[record.record_id] = record
        return sorted(deduplicated.values(), key=lambda item: (-item.score, item.record_id))[: query.top_k_recall]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """对话写短期态；长期按记录类型分派，失败不吞掉以免伪造成功。"""
        if record.record_type == "conversation" and self.short_term is not None:
            await self.short_term.append(record, trace=trace)
        target = self.knowledge if record.record_type == "knowledge" else self.conversation
        if target is not None:
            await target.append(record, trace=trace)

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """向全部存储传播撤权，任一失败都阻止上层继续当作已遗忘。"""
        for store in (self.short_term, self.conversation, self.knowledge):
            if store is not None:
                await store.forget(source_id, trace=trace)
