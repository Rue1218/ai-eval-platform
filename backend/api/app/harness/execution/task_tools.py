"""Harness 执行层：platform.tasks 长任务 MCP 工具（P4-1）。

``create_task_safe`` / ``status_task_safe`` / ``cancel_task_safe`` 是
``platform.tasks`` MCP 工具的执行体：**只入 PG 队列或查询，不等待 Worker 终态、
不轮询**（§7.4 长任务桥接）。会话/用户归属由 ``ToolExecutionContext`` 注入
（平台来源，模型不可传）；DB Session 自管（``with_managed_session`` 语义，
EX-6），handler 内 lazy import 避免包初始化循环。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.errors import AppError, ErrorCode

from .worker_bridge import TASK_KINDS, enqueue_long_task

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def _context_ids(context: object) -> tuple[str, str]:
    """提取平台注入的 session_id/user_id；缺失即拒绝（模型不可伪造）。"""
    session_id = str(getattr(context, "session_id", "") or "")
    user_id = str(getattr(context, "user_id", "") or "")
    if not session_id or not user_id:
        raise AppError(ErrorCode.VALIDATION, "缺少工具上下文")
    return session_id, user_id


def create_task_safe(arguments: Mapping[str, object], context: object) -> dict:
    """platform.tasks.create：直接入队（short 工具）。

    返回 ``{status: "queued", task_id, kind}``（§7.4 契约），真实进度/报告/错误
    由 Worker 写 ``ws_events``。门禁：kind 合法；会话归属可见；无待确认卡
    （防绕过确认）；会话无活动任务（占槽）；stress 须由已成功的 benchmark/rag
    父任务派生（先评后压）；非 stress 须带 ``dataset_id``；唯一索引冲突 →
    CONCURRENCY。
    """
    session_id, user_id = _context_ids(context)
    kind = str(arguments.get("kind") or "")
    if kind not in TASK_KINDS:
        raise AppError(ErrorCode.VALIDATION, f"未知任务类型：{kind}")
    from sqlalchemy.exc import IntegrityError

    from app.config import settings
    from app.db import SessionLocal
    from app.harness.memory.episodic import get_active_tasks
    from app.models import AuditLog, Task
    from app.session_access import require_visible_session

    from .worker_bridge import count_active_tasks

    db = SessionLocal()
    try:
        session = require_visible_session(db, session_id, user_id)
        if session.pending_confirm:
            raise AppError(ErrorCode.CONCURRENCY, "会话存在待确认任务，请先确认或取消")
        if get_active_tasks(db, session_id):
            raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务")
        # P4-2 资源配额：每用户活动任务上限（审计拒绝事件）
        if count_active_tasks(db, user_id=user_id) >= settings.max_active_tasks_per_user:
            db.add(
                AuditLog(
                    user_id=user_id,
                    action="task_quota_rejected",
                    target_type="user",
                    target_id=user_id,
                    detail={"kind": kind, "limit": settings.max_active_tasks_per_user},
                )
            )
            db.commit()
            raise AppError(ErrorCode.CONCURRENCY, "达到个人任务配额上限，请等待现有任务结束后再发起")
        if kind == "stress":
            parent_id = str(arguments.get("parent_task_id") or "")
            parent = db.get(Task, parent_id) if parent_id else None
            if (
                not parent
                or parent.status != "succeeded"
                or parent.kind not in {"benchmark", "rag"}
            ):
                raise AppError(ErrorCode.VALIDATION, "压测任务须由已成功的质量任务派生")
        elif not arguments.get("dataset_id"):
            raise AppError(ErrorCode.VALIDATION, "缺少数据集")
        spec = {key: value for key, value in arguments.items() if key != "kind"}
        parent_task_id = spec.pop("parent_task_id", None)
        try:
            task_id = enqueue_long_task(
                db,
                session_id=session_id,
                user_id=user_id,
                kind=kind,
                spec=spec,
                parent_task_id=str(parent_task_id) if parent_task_id else None,
            )
        except IntegrityError:
            db.rollback()
            raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务") from None
        return {"status": "queued", "task_id": task_id, "kind": kind}
    finally:
        db.close()


def status_task_safe(arguments: Mapping[str, object], context: object) -> dict:
    """platform.tasks.status：只读查询，不等待终态、不轮询。"""
    _session_id, user_id = _context_ids(context)
    task_id = str(arguments.get("task_id") or "")
    if not task_id:
        raise AppError(ErrorCode.VALIDATION, "缺少 task_id")
    from app.db import SessionLocal
    from app.models import Task

    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
        if task.created_by != user_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "没有权限查看该任务")
        return {
            "task_id": task.id,
            "kind": task.kind,
            "status": task.status,
            "progress": dict(task.progress or {}),
            "report_id": task.report_id,
        }
    finally:
        db.close()


def cancel_task_safe(arguments: Mapping[str, object], context: object) -> dict:
    """platform.tasks.cancel：行锁取消非终态任务；终态幂等返回现状。"""
    _session_id, user_id = _context_ids(context)
    task_id = str(arguments.get("task_id") or "")
    if not task_id:
        raise AppError(ErrorCode.VALIDATION, "缺少 task_id")
    from app.db import SessionLocal
    from app.models import AuditLog, Task, TaskEvent

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
        if not task:
            raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
        if task.created_by != user_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事")
        if task.status in _TERMINAL_STATUSES:
            return {"task_id": task.id, "status": task.status, "kind": task.kind}
        now = datetime.now(UTC)
        task.status = "cancelled"
        task.finished_at = now
        task.cancel_requested_at = now
        task.progress = {**(task.progress or {}), "message": "任务已取消"}
        db.add(
            TaskEvent(
                task_id=task.id,
                event="cancelled",
                level="info",
                message="任务已取消",
                payload={"status": "cancelled"},
            )
        )
        db.add(
            AuditLog(
                user_id=user_id,
                action="task_cancel",
                target_type="task",
                target_id=task.id,
                detail={"kind": task.kind},
            )
        )
        db.commit()
        return {"task_id": task.id, "status": "cancelled", "kind": task.kind}
    finally:
        db.close()
