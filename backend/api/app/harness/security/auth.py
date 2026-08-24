"""Harness 跨层安全：确认卡行锁与归属校验（M8 阶段 4）。

``lock_pending_confirm`` 为**唯一行锁入口**（SELECT ... FOR UPDATE 读
``sessions.pending_confirm`` + ``pending_confirm_author_id``）；owner 校验与
并发检测**复用已取得的行锁 PendingConfirm**，不再单独行锁（避免重复锁）。
M4 ``handle_confirm_ack`` 全程同一 DB 事务、单次行锁。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.errors import AppError, ErrorCode


@dataclass(frozen=True, slots=True)
class PendingConfirm:
    """行锁读出的确认卡状态。"""

    pending: dict | None  # sessions.pending_confirm JSONB
    author_id: str | None  # pending_confirm_author_id


def lock_pending_confirm(db, session_id: str) -> PendingConfirm:
    """SELECT ... FOR UPDATE 行锁读 sessions.pending_confirm + author_id。

    返回 PendingConfirm；无卡时 pending=None。
    **唯一行锁入口**：M4 confirm.py 应先调本函数取得行锁 + PendingConfirm，
    再在同一事务内做 owner 校验与并发检测。
    """
    row = db.execute(
        text(
            "SELECT pending_confirm, pending_confirm_author_id "
            "FROM sessions WHERE id = :session_id FOR UPDATE"
        ),
        {"session_id": session_id},
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    return PendingConfirm(
        pending=row.pending_confirm if row.pending_confirm is not None else None,
        author_id=row.pending_confirm_author_id,
    )


def assert_confirm_owner(pending: PendingConfirm, user_id: str) -> None:
    """owner 校验（OR-8）；复用已取得的行锁 PendingConfirm。

    无卡 → AppError(VALIDATION, "无待确认卡")；
    非 owner → AppError(UNAUTHORIZED, "无权操作确认卡")（不泄露具体原因）。
    """
    if pending.pending is None:
        raise AppError(ErrorCode.VALIDATION, "无待确认卡")
    if pending.author_id is None or pending.author_id != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "无权操作确认卡")


def assert_no_concurrent_confirm(pending: PendingConfirm) -> None:
    """并发确认检测；复用同一事务内已取得的行锁 PendingConfirm。

    若卡已被消费 → AppError(CONCURRENCY, "确认卡已被处理")。
    """
    if pending.pending is None:
        raise AppError(ErrorCode.CONCURRENCY, "确认卡已被处理")
