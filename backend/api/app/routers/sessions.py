"""Agent 会话及历史回放 REST 接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import Message, Task, User, WsEvent
from ..models import Session as AgentSession
from ..schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
ACTIVE_STATUSES = {"queued", "running", "awaiting_case_confirm"}


def _owned_session(db: Session, session_id: str, user_id: str) -> AgentSession:
    """读取当前成员拥有的会话，阻止通过 UUID 越权访问会话历史。"""
    session = (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id, AgentSession.user_id == user_id)
        .first()
    )
    if not session:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    return session


@router.get("")
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前成员会话和至多一个非终态任务摘要。"""
    rows = (
        db.query(AgentSession)
        .filter(AgentSession.user_id == user.id)
        .order_by(AgentSession.updated_at.desc())
        .all()
    )
    items = []
    for row in rows:
        task = (
            db.query(Task)
            .filter(Task.session_id == row.id, Task.status.in_(ACTIVE_STATUSES))
            .order_by(Task.created_at.desc())
            .first()
        )
        value = SessionOut.model_validate(row).model_dump(mode="json")
        value["active_task"] = (
            {"id": task.id, "kind": task.kind, "status": task.status} if task else None
        )
        items.append(value)
    return {"items": items, "total": len(items)}


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建尚未关联长任务的空 Agent 会话。"""
    session = AgentSession(user_id=user.id, title=body.title.strip())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}/messages")
def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """回放用户/助手文本与确认卡等 WebSocket 历史事件。"""
    _owned_session(db, session_id, user.id)
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
    return {
        "messages": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "attachments": row.attachments,
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
    }


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除会话及其对话记录；关联任务与会话解绑后在任务页保留。"""
    session = _owned_session(db, session_id, user.id)
    db.query(Message).filter(Message.session_id == session_id).delete(synchronize_session=False)
    db.query(WsEvent).filter(WsEvent.session_id == session_id).delete(synchronize_session=False)
    # 任务属独立评测资产，仅解除会话关联（tasks.session_id 置空），不在任务页消失
    db.query(Task).filter(Task.session_id == session_id).update(
        {Task.session_id: None}, synchronize_session=False
    )
    db.delete(session)
    db.commit()
    return {"ok": True}
