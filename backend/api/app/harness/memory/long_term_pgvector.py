"""同 PostgreSQL 的 pgvector 长期知识存储；先 ACL/撤权，再计算相似度。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.errors import AppError, ErrorCode
from app.harness.contracts.memory import (
    MemoryPort,
    MemoryQuery,
    MemoryRecord,
    validate_memory_query,
)
from app.harness.contracts.trace import TraceContext
from app.models import KnowledgeMemory

from .knowledge_store import lexical_score, record_is_authorized, vector_score


class PgvectorMemoryStore(MemoryPort):
    """pgvector 业务表的 Port 适配；没有授权来源时绝不返回知识记录。"""

    def __init__(self, db: Session) -> None:
        self._db = db

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """SQL 先过滤租户、撤权和来源白名单，随后以向量或词项相似度排序。"""
        validate_memory_query(query, trace)
        if "knowledge" not in query.record_types or not query.permitted_resource_ids:
            return []
        rows = (
            self._db.query(KnowledgeMemory)
            .filter(
                KnowledgeMemory.tenant_id == query.tenant_id,
                KnowledgeMemory.memory_revoked.is_(False),
                KnowledgeMemory.source_id.in_(query.permitted_resource_ids),
            )
            .all()
        )
        records: list[MemoryRecord] = []
        for row in rows:
            if not record_is_authorized(acl_user_ids=row.acl_user_ids, user_id=query.user_id):
                continue
            score = vector_score(query.query_embedding, row.embedding)
            records.append(
                MemoryRecord(
                    record_id=row.id,
                    source_id=row.source_id,
                    version=row.source_version,
                    text=row.content,
                    record_type="knowledge",
                    timestamp=row.updated_at.isoformat() if row.updated_at else "",
                    score=score if score is not None else lexical_score(query.query_text, row.content),
                    acl=row.acl,
                    origin_trace_id=row.origin_trace_id,
                    origin_span_id=row.origin_span_id,
                    metadata=dict(row.meta or {}),
                )
            )
        return sorted(records, key=lambda item: (-item.score, item.record_id))[: query.top_k_recall]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """写入知识向量及 provenance；未知租户或来源不允许降级为全局知识。"""
        if not record.source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "知识记忆缺少来源")
        metadata: dict[str, Any] = record.metadata if isinstance(record.metadata, dict) else {}
        tenant_id = str(metadata.get("tenant_id") or "")
        if not tenant_id:
            raise AppError(ErrorCode.VALIDATION, "知识记忆缺少租户")
        row = self._db.query(KnowledgeMemory).filter(KnowledgeMemory.id == record.record_id).first()
        if row is None:
            row = KnowledgeMemory(id=record.record_id, tenant_id=tenant_id, source_id=record.source_id, content=record.text)
            self._db.add(row)
        row.tenant_id = tenant_id
        row.source_id = record.source_id
        row.source_version = record.version
        row.content = record.text
        row.embedding = metadata.get("embedding")
        row.meta = {key: value for key, value in metadata.items() if key != "embedding"}
        row.acl = record.acl
        row.acl_user_ids = list(metadata.get("allowed_user_ids") or [])
        row.origin_trace_id = record.origin_trace_id or trace.trace_id
        row.origin_span_id = record.origin_span_id or trace.span_id
        row.memory_revoked = False
        self._db.flush()

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """撤权仅标记知识记录，保留审计数据但阻断所有后续相似度检索。"""
        if not source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "记忆来源不可为空")
        self._db.query(KnowledgeMemory).filter(KnowledgeMemory.source_id == source_id).update(
            {KnowledgeMemory.memory_revoked: True}, synchronize_session=False
        )
        self._db.flush()
