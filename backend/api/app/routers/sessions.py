"""Agent 会话及历史回放 REST 接口。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Message, Task, User, WsEvent
from ..models import Session as AgentSession
from ..schemas import SessionCreate, SessionOut, SessionSharingUpdate
from ..session_access import require_session_owner, require_visible_session
from ..session_connections import SESSION_CONNECTION_HUB

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
ACTIVE_STATUSES = {"queued", "running", "awaiting_case_confirm"}


def _session_out(db: Session, row: AgentSession, user: User) -> dict:
    """补齐会话 owner、当前成员管理权和活动任务摘要。"""
    task = (
        db.query(Task)
        .filter(Task.session_id == row.id, Task.status.in_(ACTIVE_STATUSES))
        .order_by(Task.created_at.desc())
        .first()
    )
    value = SessionOut.model_validate(row).model_dump(mode="json")
    value["can_manage"] = row.user_id == user.id
    value["can_delete"] = row.user_id == user.id
    value["active_task"] = (
        {"id": task.id, "kind": task.kind, "status": task.status} if task else None
    )
    return value


@router.get("")
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前成员创建的私有会话及全团队共享的未删除会话。"""
    rows = (
        db.query(AgentSession)
        .filter(
            AgentSession.deleted_at.is_(None),
            or_(AgentSession.user_id == user.id, AgentSession.visibility == "team"),
        )
        .order_by(AgentSession.updated_at.desc())
        .all()
    )
    items = [_session_out(db, row, user) for row in rows]
    return {"items": items, "total": len(items)}


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建尚未关联长任务的空 Agent 会话，默认仅创建者可见。"""
    session = AgentSession(
        user_id=user.id,
        title=body.title.strip(),
        visibility=body.visibility,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_out(db, session, user)


@router.put("/{session_id}/sharing", response_model=SessionOut)
async def update_session_sharing(
    session_id: str,
    body: SessionSharingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """由会话创建者在私有和全团队共享之间切换可见范围。"""
    session = require_session_owner(db, session_id, user.id, lock=True)
    session.visibility = body.visibility
    db.add(
        AuditLog(
            user_id=user.id,
            action="session_sharing_update",
            target_type="session",
            target_id=session.id,
            detail={"visibility": body.visibility},
        )
    )
    db.commit()
    db.refresh(session)
    # 从 team 收回到 private 时主动中断协作者连接，避免继续收到瞬态流。
    if session.visibility == "private":
        await SESSION_CONNECTION_HUB.close_non_owner(session.id, session.user_id)
    return _session_out(db, session, user)


@router.get("/{session_id}/messages")
def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """回放用户/助手文本与确认卡等 WebSocket 历史事件。"""
    session = require_visible_session(db, session_id, user.id)
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at, Message.id)
        .all()
    )
    events = (
        db.query(WsEvent)
        .filter(WsEvent.session_id == session_id)
        .order_by(WsEvent.event_id)
        .all()
    )
    author_ids = {row.author_id for row in messages if row.author_id}
    if session.pending_confirm_author_id:
        author_ids.add(session.pending_confirm_author_id)
    authors = (
        db.query(User).filter(User.id.in_(author_ids)).all() if author_ids else []
    )
    author_map = {
        row.id: {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
        }
        for row in authors
    }
    return {
        "messages": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "attachments": row.attachments,
                "author_id": row.author_id,
                "author": author_map.get(row.author_id),
                "client_message_id": row.client_message_id,
                # assistant 交付句回复耗时（毫秒），仅 assistant 非空；前端气泡展示「耗时 x 秒」。
                "latency_ms": row.latency_ms,
                "model_name": row.model_name,
                "profile_id": row.profile_id,
                "profile_name": row.profile_name,
                "provider": row.provider,
                "created_at": row.created_at,
            }
            for row in messages
        ],
        "events": [
            {
                "event_id": row.event_id,
                "event": row.event,
                "task_id": row.task_id,
                "payload": row.payload,
                "ts": row.ts,
            }
            for row in events
        ],
        "pending_confirm": session.pending_confirm,
        "pending_confirm_author_id": session.pending_confirm_author_id,
        "pending_confirm_author": author_map.get(session.pending_confirm_author_id),
        # 新 Agent 上下文模型尚未确定，暂时不计算旧 ContextMeter。
        "compact_summary": session.compact_summary,
        "context_meter": None,
    }


@router.delete("/{session_id}", status_code=204, response_class=Response)
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """软删除空闲会话，不物理删除审计消息、事件、任务或报告。"""
    session = require_session_owner(db, session_id, user.id, lock=True)
    if session.pending_confirm:
        raise AppError(ErrorCode.VALIDATION, "存在待确认任务，请先确认或取消后再删除会话")
    active_task = (
        db.query(Task)
        .filter(Task.session_id == session.id, Task.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if active_task:
        raise AppError(ErrorCode.VALIDATION, "存在执行中的任务，请先取消或等待任务结束")

    session.deleted_at = datetime.now(UTC)
    db.add(
        AuditLog(
            user_id=user.id,
            action="session_delete",
            target_type="session",
            target_id=session.id,
            detail={"mode": "soft_delete"},
        )
    )
    db.commit()
    # 删除完成后统一断开 owner 与协作者。
    await SESSION_CONNECTION_HUB.close_all(session.id)
    return Response(status_code=204)
