"""PostgreSQL 对话归档 Port：只从既有 messages 表召回，不把存储细节泄漏给 Context。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from app.models import Message
from app.models import Session as AgentSession

from .session_context_store import SessionContextStore


def _metadata_scope(metadata: dict[str, Any], *, trace: TraceContext) -> MemoryQuery:
    """从记录 metadata 还原受限检索范围，写入操作也必须经过同一归属校验。"""
    return MemoryQuery(
        query_text="conversation-write",
        tenant_id=str(metadata.get("tenant_id") or ""),
        user_id=str(metadata.get("user_id") or ""),
        session_id=str(metadata.get("session_id") or ""),
        trace_id=trace.trace_id,
    )


def _message_source_id(message_id: str) -> str:
    """消息表主键是对话记忆唯一来源，避免把正文或敏感字段塞进 source_id。"""
    return f"message:{message_id}"


def _message_id_from_source(source_id: str) -> str:
    """只接受本 Port 管理的消息来源标识，防止 forget 误操作其他存储。"""
    prefix = "message:"
    message_id = source_id.removeprefix(prefix).strip() if source_id.startswith(prefix) else ""
    if not message_id:
        raise AppError(ErrorCode.VALIDATION, "对话记忆来源格式无效")
    return message_id


@dataclass
class ConversationMemoryPort(MemoryPort):
    """使用既有 messages 表的会话归档实现；会话消息只能在原 owner 范围内召回。"""

    db: DbSession
    tenant_id: str

    def _record(self, row: Message, *, owner_id: str, session_id: str) -> MemoryRecord:
        """将已授权的消息行转换为带来源、角色和 trace 溯源的候选记录。"""
        created_at = getattr(row, "created_at", None)
        timestamp = created_at.isoformat() if hasattr(created_at, "isoformat") else ""
        return MemoryRecord(
            record_id=_message_source_id(str(row.id)),
            source_id=_message_source_id(str(row.id)),
            text=str(row.content or ""),
            record_type="conversation",
            timestamp=timestamp,
            acl="session",
            origin_trace_id=getattr(row, "origin_trace_id", None),
            origin_span_id=getattr(row, "origin_span_id", None),
            metadata={
                "tenant_id": self.tenant_id,
                "user_id": owner_id,
                "session_id": session_id,
                "role": str(row.role or "user"),
            },
        )

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """按 owner、会话、角色和撤权标记读取对话；越权范围统一视为无可见记录。"""
        validate_memory_query(query, trace)
        if query.tenant_id != self.tenant_id or "conversation" not in query.record_types:
            return []
        try:
            session = (
                self.db.query(AgentSession)
                .filter(
                    AgentSession.id == query.session_id,
                    AgentSession.user_id == query.user_id,
                    AgentSession.deleted_at.is_(None),
                )
                .first()
            )
            # SQL 条件和结果值双重核对：测试桩或异常 ORM 行为也不能越过 owner 边界。
            if session is None or str(session.user_id) != query.user_id:
                return []
            # 先按压缩游标保留完整时序，再过滤撤权消息；否则游标被撤权时会重召回旧原文。
            rows = SessionContextStore(self.db).conversation_rows(
                session,
                session_id=query.session_id,
            )
            rows = [row for row in rows if not bool(getattr(row, "memory_forgotten", False))]
        except AppError:
            raise
        except Exception as exc:
            agent_trace(f"memory PG读取异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
        return [
            self._record(row, owner_id=query.user_id, session_id=query.session_id)
            for row in rows[-query.top_k_recall :]
        ]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """为已授权会话的既有消息补回 trace 溯源；消息正文仍只由正常流程写入。"""
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        query = _metadata_scope(metadata, trace=trace)
        validate_memory_query(query, trace)
        if query.tenant_id != self.tenant_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "无权写入其他租户的对话记忆")
        message_id = _message_id_from_source(record.source_id)
        try:
            session = (
                self.db.query(AgentSession)
                .filter(
                    AgentSession.id == query.session_id,
                    AgentSession.user_id == query.user_id,
                    AgentSession.deleted_at.is_(None),
                )
                .first()
            )
            # 写入侧与 retrieve 使用同一 owner 校验，不能只相信调用方构造的 metadata。
            if session is None or str(session.user_id) != query.user_id:
                raise AppError(ErrorCode.UNAUTHORIZED, "无权写入该会话的对话记忆")
            row = (
                self.db.query(Message)
                .filter(Message.id == message_id, Message.session_id == query.session_id)
                .first()
            )
            if row is None or str(row.session_id) != query.session_id:
                raise AppError(ErrorCode.NOT_FOUND, "对话记忆来源不存在")
            row.origin_trace_id = record.origin_trace_id or trace.trace_id
            row.origin_span_id = record.origin_span_id or trace.span_id
            self.db.commit()
        except AppError:
            raise
        except Exception as exc:
            self.db.rollback()
            agent_trace(f"memory PG写入异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """撤权只屏蔽后续记忆召回，不删除产品历史与审计消息。"""
        message_id = _message_id_from_source(source_id)
        try:
            row = self.db.query(Message).filter(Message.id == message_id).first()
            if row is None:
                return
            row.memory_forgotten = True
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            agent_trace(f"memory PG撤权异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
