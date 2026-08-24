"""Harness 压缩记忆（M3 阶段 3，MEM-3）。

摘要为**派生状态**（`sessions.compact_summary`），不视为唯一真相：原始记录
与摘要冲突时**原始优先**（window.py 装配仍以原始消息为准）。摘要文本由
M2 ``compact.py`` 产出，本模块只负责写库/读库。
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def write_summary(db: Session, session_id: str, summary: str) -> None:
    """写 sessions.compact_summary（MEM-3 派生状态）。"""
    from app.models import Session as AgentSession

    session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
    if session is None:
        return
    session.compact_summary = summary
    db.commit()


def get_summary(db: Session, session_id: str) -> str | None:
    """读 compact_summary，供 M2 assembly.py 装配。"""
    from app.models import Session as AgentSession

    session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
    if session is None:
        return None
    return session.compact_summary
