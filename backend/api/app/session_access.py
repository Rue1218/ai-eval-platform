"""Agent 会话的统一可见性与创建者权限判断。

会话仍是单一内部团队中的协作资产：``team`` 会话对当前全部正常成员可读写，
``private`` 仅创建者可访问。分享设置与软删除始终只允许创建者操作。
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .errors import AppError, ErrorCode
from .models import Session as AgentSession


def can_access_session(session: AgentSession, user_id: str) -> bool:
    """判断成员是否可读写未删除会话，供单元测试和内存策略复用。"""
    return bool(
        getattr(session, "deleted_at", None) is None
        and (
            session.user_id == user_id
            or getattr(session, "visibility", "private") == "team"
        )
    )


def is_session_owner(session: AgentSession, user_id: str) -> bool:
    """判断成员是否为会话创建者（owner）。"""
    return session.user_id == user_id


def find_visible_session(
    db: Session,
    session_id: str,
    user_id: str,
    *,
    lock: bool = False,
) -> AgentSession | None:
    """查询当前成员可访问且未软删除的会话；可选锁住会话行处理竞态。"""
    query = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.deleted_at.is_(None),
        or_(AgentSession.user_id == user_id, AgentSession.visibility == "team"),
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def require_visible_session(
    db: Session,
    session_id: str,
    user_id: str,
    *,
    lock: bool = False,
) -> AgentSession:
    """取得可见会话；私有、已删除和不存在统一不泄露为 NOT_FOUND。"""
    session = find_visible_session(db, session_id, user_id, lock=lock)
    if not session:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    return session


def require_session_owner(
    db: Session,
    session_id: str,
    user_id: str,
    *,
    lock: bool = False,
) -> AgentSession:
    """取得未删除会话并要求当前成员为 owner，区分不存在与越权。"""
    query = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    session = query.first()
    if not session:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    if not is_session_owner(session, user_id):
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限管理该会话")
    return session
