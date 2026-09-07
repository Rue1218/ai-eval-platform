"""Worker 共用事件助手：WS 事件号分配（行锁防撞号）。

从 ``main.py`` 抽出供主循环与各执行器共用；分配事件号前先锁定会话行
（与 api 侧 ``_next_event_id`` 同一把行锁），避免 Worker 与 API 并发写
同一会话时事件号撞号。
"""

from __future__ import annotations

import logging

from shared.event_vocab import EVENT_VERSION

from .db import SessionLocal
from .models import Session, WsEvent

logger = logging.getLogger("worker.events")

# #4 D3：落库 payload 内嵌的词汇版本保留字段（与 api 侧 ws.py 同构；转发/回放剥离）
_EVENT_VERSION_KEY = "event_version"


def push_ws(session_id: str | None, event: str, payload: dict, task_id: str | None = None) -> None:
    """向会话事件表追加标准事件；task_id 独立成列，payload 仅存事件数据。

    #4 D3：写库 payload 注入 ``event_version`` 词汇版本保留字段（与 api
    ``_emit_persistent`` 同构），使 api ``_forward_loop`` 具备版本一致性校验面；
    版本常量来自 shared.event_vocab（词汇表单一事实源，禁止本地自持常量）。
    """
    if not session_id:
        return
    stored_payload = dict(payload)
    stored_payload[_EVENT_VERSION_KEY] = EVENT_VERSION
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
                payload=stored_payload,
            )
        )
        db.commit()
    except Exception:
        # 事件推送失败不影响任务本体执行；重连后可经 REST 历史回放补齐
        db.rollback()
        logger.exception("push_ws failed (session=%s event=%s)", session_id, event)
    finally:
        db.close()
