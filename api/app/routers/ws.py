import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Message, Session as DBSession, User, WsEvent
from ..security import TOKEN_TYPE_WS, decode_token

router = APIRouter(tags=["ws"])


def _user_from_ticket(ticket: str) -> User | None:
    try:
        payload = decode_token(ticket)
    except Exception:
        return None
    if payload.get("type") != TOKEN_TYPE_WS:
        return None
    db: Session = SessionLocal()
    try:
        return db.query(User).filter(User.id == payload["sub"], User.disabled.is_(False)).first()
    finally:
        db.close()


def _next_event_id(db: Session, session_id: str) -> int:
    row = db.query(func.max(WsEvent.event_id)).filter(WsEvent.session_id == session_id).scalar()
    return (row or 0) + 1


async def _emit(db: Session, ws: WebSocket, session_id: str, event: str, payload: dict) -> int:
    event_id = _next_event_id(db, session_id)
    db.add(WsEvent(session_id=session_id, event_id=event_id, event=event, payload=payload))
    db.commit()
    body = {"event": event, "session_id": session_id, "event_id": event_id, **payload}
    await ws.send_json(body)
    return event_id


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    ticket = websocket.query_params.get("ticket", "")
    user = _user_from_ticket(ticket)
    if not user:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    db: Session = SessionLocal()
    try:
        # 建立 / 复用会话
        session_id = websocket.query_params.get("session_id") or None
        if session_id:
            dbs = db.query(DBSession).filter(DBSession.id == session_id).first()
            if not dbs:
                dbs = DBSession(id=session_id, user_id=user.id)
                db.add(dbs)
                db.commit()
        else:
            dbs = DBSession(user_id=user.id, title="新会话")
            db.add(dbs)
            db.commit()
            session_id = dbs.id

        # 重连补发 last_event_id 之后的事件
        last_event_id = int(websocket.query_params.get("last_event_id", "0") or 0)
        if last_event_id:
            rows = (
                db.query(WsEvent)
                .filter(WsEvent.session_id == session_id, WsEvent.event_id > last_event_id)
                .order_by(WsEvent.event_id)
                .all()
            )
            for r in rows:
                await websocket.send_json(
                    {"event": r.event, "session_id": session_id, "event_id": r.event_id, **r.payload}
                )

        await _emit(
            db, websocket, session_id, "thought",
            {"message": "你好，我是评测工程师助手，请描述你要执行的评测任务。"},
        )

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                await websocket.send_json({"event": "pong", "session_id": session_id})
                continue

            if mtype == "user_message":
                text = msg.get("text", "")
                db.add(Message(session_id=session_id, role="user", content=text))
                db.commit()

                await _emit(
                    db, websocket, session_id, "thought",
                    {"message": "已收到，正在生成确认卡（骨架版，暂不执行真实评测）。"},
                )
                await _emit(
                    db, websocket, session_id, "confirm",
                    {
                        "card": {
                            "kind": "benchmark",
                            "profile_ids": [],
                            "dataset_id": None,
                            "run": {"sample_size": 100, "concurrency": 4, "timeout_s": 60},
                            "with_stress": False,
                        }
                    },
                )
                continue

    except WebSocketDisconnect:
        pass
    finally:
        db.close()
