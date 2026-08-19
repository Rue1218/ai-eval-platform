"""Worker 共用事件助手：WS 事件号分配（行锁防撞号）。

从 ``main.py`` 抽出供主循环与各执行器共用；分配事件号前先锁定会话行
（与 api 侧 ``_next_event_id`` 同一把行锁），避免 Worker 与 API 并发写
同一会话时事件号撞号。
"""

from __future__ import annotations

import logging

from .db import SessionLocal
from .models import Session, WsEvent

logger = logging.getLogger("worker.events")


def push_ws(session_id: str | None, event: str, payload: dict, task_id: str | None = None) -> None:
    """向会话事件表追加标准事件；task_id 独立成列，payload 仅存事件数据。"""
    if not session_id:
        return
    db = SessionLocal()
    try:
        locked = db.query(Session.id).filter(Session.id == session_id).with_for_update().first()
        if not locked:
            return
        max_eid = (
            db.query(WsEvent.event_id)
            .filter(WsEvent.session_id == session_id)
            .order_by(WsEvent.event_id.desc())
            .first()
        )
        event_id = (max_eid[0] + 1) if max_eid else 1
        db.add(
            WsEvent(
                session_id=session_id,
                task_id=task_id,
                event_id=event_id,
                event=event,
                payload=payload,
            )
        )
        db.commit()
    except Exception:
        # 事件推送失败不影响任务本体执行；重连后可经 REST 历史回放补齐
        db.rollback()
        logger.exception("push_ws failed (session=%s event=%s)", session_id, event)
    finally:
        db.close()
