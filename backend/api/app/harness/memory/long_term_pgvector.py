"""pgvector 长期知识记忆：ACL 过滤、向量召回与撤权均限制在 MemoryPort 边界。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.agent.log import agent_trace
from app.errors import AppError, ErrorCode
from app.harness.contracts.memory import (
    MemoryPort,
    MemoryQuery,
    MemoryRecord,
    validate_memory_query,
)
from app.harness.contracts.trace import TraceContext

from .ports import _validate_append_scope, is_record_visible

_RETRIEVE_SQL = text(
    """
    SELECT
        record_id, source_id, version, content, acl, origin_trace_id, origin_span_id,
        tenant_id, user_id, session_id, allowed_user_ids, metadata, created_at,
        1 - (embedding <=> CAST(:query_embedding AS vector)) AS score
    FROM memory_knowledge
    WHERE tenant_id = :tenant_id
      AND memory_forgotten IS FALSE
      AND source_id = ANY(CAST(:permitted_resource_ids AS text[]))
      AND (user_id IS NULL OR user_id = :user_id)
      AND (session_id IS NULL OR session_id = :session_id)
      AND (allowed_user_ids = '[]'::jsonb OR allowed_user_ids ? :user_id)
    ORDER BY embedding <=> CAST(:query_embedding AS vector), record_id
    LIMIT :top_k_recall
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO memory_knowledge (
        record_id, source_id, version, tenant_id, user_id, session_id, allowed_user_ids,
        content, embedding, acl, origin_trace_id, origin_span_id, metadata, memory_forgotten,
        created_at, updated_at
    ) VALUES (
        :record_id, :source_id, :version, :tenant_id, :user_id, :session_id,
        CAST(:allowed_user_ids AS jsonb), :content, CAST(:embedding AS vector), :acl,
        :origin_trace_id, :origin_span_id, CAST(:metadata AS jsonb), FALSE, NOW(), NOW()
    )
    ON CONFLICT (record_id) DO UPDATE SET
        source_id = EXCLUDED.source_id,
        version = EXCLUDED.version,
        tenant_id = EXCLUDED.tenant_id,
        user_id = EXCLUDED.user_id,
        session_id = EXCLUDED.session_id,
        allowed_user_ids = EXCLUDED.allowed_user_ids,
        content = EXCLUDED.content,
        embedding = EXCLUDED.embedding,
        acl = EXCLUDED.acl,
        origin_trace_id = EXCLUDED.origin_trace_id,
        origin_span_id = EXCLUDED.origin_span_id,
        metadata = EXCLUDED.metadata,
        memory_forgotten = FALSE,
        updated_at = NOW()
    """
)

_FORGET_SQL = text(
    """
    UPDATE memory_knowledge
    SET memory_forgotten = TRUE, updated_at = NOW()
    WHERE source_id = :source_id AND tenant_id = :tenant_id
    """
)


def _vector_literal(values: list[float]) -> str:
    """将已由契约校验的浮点数组编码为 pgvector 参数，而非拼接用户原文 SQL。"""
    return "[" + ",".join(format(value, ".17g") for value in values) + "]"


def _optional_metadata_id(metadata: dict[str, Any], key: str) -> str | None:
    """读取可选的 user/session 归属；空值统一入库为 NULL 以便 SQL ACL 判断。"""
    value = str(metadata.get(key) or "").strip()
    return value or None


def _allowed_user_ids(metadata: dict[str, Any]) -> list[str]:
    """校验显式用户白名单，避免 JSON 结构异常导致数据库 ACL 条件失真。"""
    value = metadata.get("allowed_user_ids", [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise AppError(ErrorCode.VALIDATION, "知识记忆的用户授权范围无效")
    return sorted(set(value))


@dataclass
class PgvectorKnowledgeMemoryPort(MemoryPort):
    """同库 pgvector 知识记忆实现；数据库先做 ACL/撤权过滤，再进行相似度排序。"""

    db: DbSession
    tenant_id: str

    def _record(self, row: Any) -> MemoryRecord:
        """用数据库的归属列覆盖 JSON 元数据，避免存量脏数据伪造 ACL。"""
        raw_metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
        metadata = {
            **raw_metadata,
            "tenant_id": str(row["tenant_id"]),
            "user_id": str(row["user_id"] or ""),
            "session_id": str(row["session_id"] or ""),
            "allowed_user_ids": list(row["allowed_user_ids"] or []),
        }
        created_at = row["created_at"]
        timestamp = created_at.isoformat() if hasattr(created_at, "isoformat") else ""
        return MemoryRecord(
            record_id=str(row["record_id"]),
            source_id=str(row["source_id"]),
            version=int(row["version"]),
            text=str(row["content"] or ""),
            record_type="knowledge",
            timestamp=timestamp,
            score=float(row["score"] or 0.0),
            acl=str(row["acl"] or "resource"),
            origin_trace_id=row["origin_trace_id"],
            origin_span_id=row["origin_span_id"],
            metadata=metadata,
        )

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """仅在拥有向量和资源授权范围时检索，避免无嵌入时伪造“无命中”。"""
        validate_memory_query(query, trace)
        if (
            query.tenant_id != self.tenant_id
            or "knowledge" not in query.record_types
            or not query.query_embedding
            or not query.permitted_resource_ids
        ):
            return []
        try:
            rows = self.db.execute(
                _RETRIEVE_SQL,
                {
                    "tenant_id": query.tenant_id,
                    "user_id": query.user_id,
                    "session_id": query.session_id,
                    "permitted_resource_ids": query.permitted_resource_ids,
                    "query_embedding": _vector_literal(query.query_embedding),
                    "top_k_recall": query.top_k_recall,
                },
            ).mappings().all()
        except AppError:
            raise
        except Exception as exc:
            self.db.rollback()
            agent_trace(f"memory pgvector读取异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
        records = [self._record(row) for row in rows]
        # SQL 已完成 ACL，Port 边界再复核一次，防范测试桩和损坏 JSON 记录绕过权限。
        return [record for record in records if is_record_visible(record, query)]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """写入带来源与嵌入的知识记录；调用方必须先完成文档授权和向量生成。"""
        _validate_append_scope(record)
        if record.record_type != "knowledge" or not record.source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "知识记忆记录无效")
        if record.version < 1 or not record.embedding:
            raise AppError(ErrorCode.VALIDATION, "知识记忆缺少版本或向量")
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        tenant_id = str(metadata.get("tenant_id") or "").strip()
        if tenant_id != self.tenant_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "无权写入其他租户的知识记忆")
        allowed_user_ids = _allowed_user_ids(metadata)
        try:
            self.db.execute(
                _UPSERT_SQL,
                {
                    "record_id": record.record_id,
                    "source_id": record.source_id,
                    "version": record.version,
                    "tenant_id": tenant_id,
                    "user_id": _optional_metadata_id(metadata, "user_id"),
                    "session_id": _optional_metadata_id(metadata, "session_id"),
                    "allowed_user_ids": json.dumps(allowed_user_ids),
                    "content": record.text,
                    "embedding": _vector_literal(record.embedding),
                    "acl": record.acl or "resource",
                    "origin_trace_id": record.origin_trace_id or trace.trace_id,
                    "origin_span_id": record.origin_span_id or trace.span_id,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )
            self.db.commit()
        except AppError:
            raise
        except Exception as exc:
            self.db.rollback()
            agent_trace(f"memory pgvector写入异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """按来源标记撤权，保留记录供审计但禁止其再次参与向量召回。"""
        if not source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "记忆来源不可为空")
        try:
            self.db.execute(
                _FORGET_SQL,
                {"source_id": source_id, "tenant_id": self.tenant_id},
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            agent_trace(f"memory pgvector撤权异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
