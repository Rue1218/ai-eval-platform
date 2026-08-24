"""Harness 情景记忆（M3 阶段 1，MEM-2）。

封装 ws_events 持久化与重放查询（断线重放已落地，本模块统一对外提供查询/
写入入口），以及会话任务查询（供 M4 占槽门禁 OR-7 使用）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Task, WsEvent


def replay_events(db: Session, session_id: str, last_event_id: int) -> list[WsEvent]:
    """按 last_event_id 补发持久化事件（MEM-2，对齐 ws.py 重放逻辑）。"""
    return (
        db.query(WsEvent)
        .filter(WsEvent.session_id == session_id, WsEvent.event_id > last_event_id)
        .order_by(WsEvent.event_id)
        .all()
    )


def next_event_id(db: Session, session_id: str) -> int:
    """计算会话内下一个单调事件号（对齐 ws.py 取号逻辑）。"""
    row = (
        db.query(WsEvent.event_id)
        .filter(WsEvent.session_id == session_id)
        .order_by(WsEvent.event_id.desc())
        .first()
    )
    return int(row[0]) + 1 if row else 1


def append_event(
    db: Session,
    session_id: str,
    event: str,
    payload: dict,
    *,
    task_id: str | None = None,
) -> int:
    """写 ws_events，返回 event_id（对齐 ws.py 取号逻辑）。"""
    event_id = next_event_id(db, session_id)
    db.add(
        WsEvent(
            session_id=session_id,
            task_id=task_id,
            event_id=event_id,
            event=event,
            payload=payload,
            ts=datetime.now(UTC),
        )
    )
    db.commit()
    return event_id


# 任务非终态集合（占槽门禁 OR-7 使用）
_ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running", "awaiting_case_confirm")


def get_active_tasks(db: Session, session_id: str) -> list[Task]:
    """查询会话非终态任务，供 M4 OR-7 占槽门禁。"""
    return (
        db.query(Task)
        .filter(Task.session_id == session_id, Task.status.in_(_ACTIVE_STATUSES))
        .all()
    )
