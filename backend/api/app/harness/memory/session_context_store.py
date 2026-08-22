"""会话上下文的 PostgreSQL 读取适配器。

本模块是 ContextMeter、/compact 与对话归档共用的存储边界。上下文工程只消费
``SessionContextMessage`` 契约，禁止重新在 Context 层查询 ORM 模型。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession

from app.harness.contracts.context import SessionContextMessage
from app.models import Message, ProtocolProfile, Setting, WsEvent
from app.models import Session as AgentSession


@dataclass
class SessionContextStore:
    """按会话读取窗口素材和持久化上下文状态的 PostgreSQL 适配器。"""

    db: DbSession

    def conversation_rows(
        self,
        session: AgentSession,
        *,
        session_id: str | None = None,
    ) -> list[Message]:
        """读取压缩游标之后的完整对话时序；调用方决定撤权过滤与截断。"""
        resolved_session_id = str(session_id or getattr(session, "id", "") or "").strip()
        if not resolved_session_id:
            return []
        rows = (
            self.db.query(Message)
            .filter(
                Message.session_id == resolved_session_id,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )
        keep_from = str(getattr(session, "compact_keep_from", "") or "").strip()
        if keep_from:
            hit_index = next((i for i, row in enumerate(rows) if str(row.id) == keep_from), None)
            if hit_index is not None:
                rows = rows[hit_index:]
        return rows

    def window_messages(
        self,
        session: AgentSession,
        *,
        max_messages: int,
    ) -> list[SessionContextMessage]:
        """按压缩游标和时间顺序读取当前可见的 user/assistant 窗口。"""
        rows = self.conversation_rows(session, session_id=str(session.id))
        if len(rows) > max_messages:
            rows = rows[-max_messages:]
        return [
            SessionContextMessage(
                id=str(row.id),
                role="assistant" if row.role == "assistant" else "user",
                content=str(row.content or ""),
            )
            for row in rows
        ]

    def capability_stats(self, session_id: str) -> tuple[bool, int]:
        """从可回放事件恢复技能和唯一短工具数；旧库或测试桩安全回退为零。"""
        try:
            events = (
                self.db.query(WsEvent)
                .filter(WsEvent.session_id == session_id)
                .order_by(WsEvent.event_id.asc())
                .all()
            )
        except Exception:
            return False, 0
        skill_seen = False
        tool_names: set[str] = set()
        for row in events:
            payload = row.payload if isinstance(row.payload, dict) else {}
            if payload.get("skill_id"):
                skill_seen = True
            if row.event == "tool_call" and payload.get("name"):
                tool_names.add(str(payload["name"]))
        return skill_seen, min(len(tool_names), 28)

    def profile_context_window(self) -> int:
        """读取当前 Agent 协议档窗口上限；缺失或异常沿用产品默认 200000。"""
        try:
            setting = self.db.query(Setting).filter(Setting.key == "agent_profile_id").first()
            if setting and setting.value:
                profile = (
                    self.db.query(ProtocolProfile)
                    .filter(ProtocolProfile.id == setting.value)
                    .first()
                )
                if profile and getattr(profile, "context_window", None):
                    return int(profile.context_window)
        except Exception:
            return 200000
        return 200000

    def save_compaction(
        self,
        session: AgentSession,
        *,
        summary: str,
        keep_from_id: str,
    ) -> None:
        """持久化摘要和保留游标；只在模型摘要有效且未取消后调用。"""
        session.compact_summary = summary
        session.compact_keep_from = keep_from_id
        self.db.commit()
