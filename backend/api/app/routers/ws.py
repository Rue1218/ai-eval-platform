"""Agent WebSocket：短票鉴权、事件持久化和断线补发。"""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Message, ProtocolProfile, StoredFile, Task, User, WsEvent
from ..models import Session as AgentSession
from ..security import TOKEN_TYPE_WS, decode_token

router = APIRouter(tags=["ws"])


def _user_from_ticket(ticket: str) -> User | None:
    """验证 WebSocket 短票、账号状态和改密后的认证版本。"""
    try:
        payload = decode_token(ticket)
    except Exception:
        return None
    if payload.get("type") != TOKEN_TYPE_WS:
        return None
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == payload.get("sub"), User.disabled.is_(False)).first()
        if not user or payload.get("av") != user.auth_version:
            return None
        return user
    finally:
        db.close()


def _next_event_id(db: Session, session_id: str) -> int:
    """在锁定会话行后获取该会话的下一个单调事件号。"""
    db.query(AgentSession).filter(AgentSession.id == session_id).with_for_update().one()
    current = db.query(func.max(WsEvent.event_id)).filter(WsEvent.session_id == session_id).scalar()
    return (current or 0) + 1


async def _emit(
    db: Session,
    ws: WebSocket,
    session_id: str,
    event: str,
    payload: dict,
    *,
    task_id: str | None = None,
) -> int:
    """持久化标准 WS 事件后向当前连接发送同一份公开载荷。"""
    event_id = _next_event_id(db, session_id)
    now = datetime.now(UTC)
    db.add(
        WsEvent(
            session_id=session_id,
            task_id=task_id,
            event_id=event_id,
            event=event,
            payload=payload,
            ts=now,
        )
    )
    db.commit()
    body = {"event": event, "session_id": session_id, "event_id": event_id, "ts": now.isoformat(), **payload}
    if task_id:
        body["task_id"] = task_id
    await ws.send_json(body)
    return event_id


def _owned_session(db: Session, session_id: str, user_id: str) -> AgentSession | None:
    """读取当前成员拥有的会话，阻止短票跨账号复用会话 ID。"""
    return (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id, AgentSession.user_id == user_id)
        .first()
    )


def _assert_attachments(db: Session, attachment_ids: list[str]) -> None:
    """确保消息引用的文件已真实上传，避免伪造附件 ID。"""
    if not attachment_ids:
        return
    count = db.query(StoredFile).filter(StoredFile.id.in_(attachment_ids)).count()
    if count != len(set(attachment_ids)):
        raise ValueError("附件不存在")


async def _send_tool_inventory(db: Session, ws: WebSocket, session_id: str) -> None:
    """用受控短工具事件返回不含 Key 的协议档发现结果。"""
    await _emit(
        db,
        ws,
        session_id,
        "tool_call",
        {"tool": "model.list", "arguments": {}},
    )
    profiles = db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.desc()).all()
    await _emit(
        db,
        ws,
        session_id,
        "tool_result",
        {
            "tool": "model.list",
            "ok": True,
            "result": {
                "items": [
                    {"id": profile.id, "name": profile.name, "protocol": profile.protocol}
                    for profile in profiles
                ]
            },
        },
    )


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    """建立 Agent 长连接，实时事件只做控制面而不执行长任务。"""
    ticket = websocket.query_params.get("ticket", "")
    user = _user_from_ticket(ticket)
    if not user:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    db: Session = SessionLocal()
    try:
        requested_session_id = websocket.query_params.get("session_id")
        if requested_session_id:
            session = _owned_session(db, requested_session_id, user.id)
            if not session:
                await websocket.close(code=4404)
                return
        else:
            session = AgentSession(user_id=user.id, title="新会话")
            db.add(session)
            db.commit()
            db.refresh(session)
        session_id = session.id

        try:
            last_event_id = max(0, int(websocket.query_params.get("last_event_id", "0") or "0"))
        except ValueError:
            last_event_id = 0
        if last_event_id:
            rows = (
                db.query(WsEvent)
                .filter(WsEvent.session_id == session_id, WsEvent.event_id > last_event_id)
                .order_by(WsEvent.event_id)
                .all()
            )
            for row in rows:
                body = {
                    "event": row.event,
                    "session_id": session_id,
                    "event_id": row.event_id,
                    "ts": row.ts.isoformat(),
                    **row.payload,
                }
                if row.task_id:
                    body["task_id"] = row.task_id
                await websocket.send_json(body)
        else:
            await _emit(
                db,
                websocket,
                session_id,
                "thought",
                {"message": "你好，我是评测工程师助手。请描述目标，或从确认卡中选择已配置的资产。"},
            )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _emit(
                    db,
                    websocket,
                    session_id,
                    "error",
                    {"code": "VALIDATION", "message": "消息格式无效"},
                )
                continue

            message_type = message.get("type")
            if message_type == "ping":
                await _emit(db, websocket, session_id, "pong", {})
                continue

            if message_type == "user_message":
                text = str(message.get("text", "")).strip()
                attachments = message.get("attachments", [])
                if not isinstance(attachments, list) or not all(isinstance(item, str) for item in attachments):
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": "VALIDATION", "message": "attachments 格式无效"},
                    )
                    continue
                if not text and not attachments:
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": "VALIDATION", "message": "消息不能为空"},
                    )
                    continue
                try:
                    _assert_attachments(db, attachments)
                except ValueError:
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": "NOT_FOUND", "message": "附件不存在"},
                    )
                    continue
                db.add(Message(session_id=session_id, role="user", content=text, attachments=attachments))
                session.updated_at = datetime.now(UTC)
                db.commit()
                await _emit(
                    db,
                    websocket,
                    session_id,
                    "thought",
                    {"message": "已收到需求，正在读取可用协议档。确认卡只会在字段完整后入队。"},
                )
                await _send_tool_inventory(db, websocket, session_id)
                continue

            if message_type == "confirm_ack":
                ok = bool(message.get("ok"))
                text = "已确认，请等待任务接口返回入队结果。" if ok else "已取消本次确认，不会创建任务。"
                await _emit(db, websocket, session_id, "thought", {"message": text})
                continue

            if message_type == "cancel_task":
                task_id = message.get("task_id")
                task = (
                    db.query(Task)
                    .filter(Task.id == task_id, Task.created_by == user.id)
                    .first()
                )
                if not task:
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": "NOT_FOUND", "message": "任务不存在"},
                    )
                else:
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "thought",
                        {"message": "已收到取消请求，任务接口将执行状态变更。"},
                        task_id=task.id,
                    )
                continue

            await _emit(
                db,
                websocket,
                session_id,
                "error",
                {"code": "VALIDATION", "message": "不支持的消息类型"},
            )
    except WebSocketDisconnect:
        pass
    finally:
        db.close()
