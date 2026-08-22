"""PostgreSQL 对话归档：消息历史只在记忆层读取，Context 不再直接访问 ORM。"""

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
from app.models import Message
from app.models import Session as AgentSession


class ConversationStore(MemoryPort):
    """既有 messages 表的长期对话适配，不改变 REST 回放数据来源。"""

    def __init__(self, db: Session) -> None:
        self._db = db

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """先校验会话可见性与软删除，再读取可作为上下文的 user/assistant 消息。"""
        validate_memory_query(query, trace)
        session = self._db.query(AgentSession).filter(AgentSession.id == query.session_id).first()
        if session is None or session.deleted_at is not None:
            return []
        if session.user_id != query.user_id and session.visibility != "team":
            return []
        # 先取最新 top_k_recall 条再还原时间序，避免长会话只召回最旧窗口。
        rows = reversed(
            
                self._db.query(Message)
                .filter(
                    Message.session_id == query.session_id,
                    Message.role.in_(("user", "assistant")),
                    Message.memory_revoked.is_(False),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(query.top_k_recall)
                .all()
            
        )
        return [
            MemoryRecord(
                record_id=row.id,
                source_id=row.source_id or f"message:{row.id}",
                version=row.source_version or 1,
                text=row.content or "",
                record_type="conversation",
                timestamp=row.created_at.isoformat() if row.created_at else "",
                score=1.0,
                acl="session",
                origin_trace_id=row.origin_trace_id,
                origin_span_id=row.origin_span_id,
                metadata={
                    "tenant_id": query.tenant_id,
                    "user_id": query.user_id,
                    "session_id": query.session_id,
                    "role": row.role,
                },
            )
            for row in rows
        ]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """将新对话记录落 messages；无会话/角色一律拒绝，避免写孤儿上下文。"""
        metadata: dict[str, Any] = record.metadata if isinstance(record.metadata, dict) else {}
        session_id = str(metadata.get("session_id") or "")
        role = str(metadata.get("role") or "")
        if not session_id or role not in {"user", "assistant"}:
            raise AppError(ErrorCode.VALIDATION, "对话记忆缺少会话或角色")
        session = self._db.query(AgentSession).filter(AgentSession.id == session_id).first()
        if session is None:
            raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
        row = self._db.query(Message).filter(Message.id == record.record_id).first()
        if row is None:
            row = Message(id=record.record_id, session_id=session_id, role=role, content=record.text)
            self._db.add(row)
        row.source_id = record.source_id
        row.source_version = record.version
        row.origin_trace_id = record.origin_trace_id or trace.trace_id
        row.origin_span_id = record.origin_span_id or trace.span_id
        # assistant 交付句的回复耗时经 metadata 透传；仅接受整数，避免脏数据进列。
        latency_ms = metadata.get("latency_ms")
        if isinstance(latency_ms, int) and not isinstance(latency_ms, bool):
            row.latency_ms = latency_ms
        # user 消息的发言人、幂等键与附件引用同样经 metadata 透传，保证 messages
        # 表的全部写入都收敛到本 Port；类型不符时忽略而不是写脏列。
        author_id = metadata.get("author_id")
        if isinstance(author_id, str) and author_id:
            row.author_id = author_id
        client_message_id = metadata.get("client_message_id")
        if isinstance(client_message_id, str) and client_message_id:
            row.client_message_id = client_message_id
        attachments = metadata.get("attachments")
        if isinstance(attachments, list):
            row.attachments = attachments
        row.memory_revoked = False
        self._db.flush()

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """只标记记忆撤权，不删除对外会话审计记录。"""
        if not source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "记忆来源不可为空")
        self._db.query(Message).filter(Message.source_id == source_id).update(
            {Message.memory_revoked: True}, synchronize_session=False
        )
        self._db.flush()
