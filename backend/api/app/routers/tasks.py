"""任务控制面：确认卡入队、状态读取、取消和重跑。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Task, TaskEvent, User
from ..models import Session as AgentSession
from ..schemas import TaskCreate, TaskDetailOut, TaskEventOut, TaskOut

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
ACTIVE_STATUSES = {"queued", "running", "awaiting_case_confirm"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def _task_out(task: Task) -> dict:
    """将任务 ORM 对象统一转换为前端需要的公开字段。"""
    return TaskOut.model_validate(task).model_dump(mode="json")


def _owned_task(db: Session, task_id: str, user_id: str) -> Task:
    """读取当前成员创建的任务，避免通过 ID 越权操作。"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    if task.created_by != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事")
    return task


def _validate_session(db: Session, session_id: str | None, user_id: str) -> None:
    """确保任务挂载的 Agent 会话存在且归当前成员所有。"""
    if not session_id:
        return
    session = (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id, AgentSession.user_id == user_id)
        .first()
    )
    if not session:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")


def _append_event(db: Session, task: Task, event: str, message: str, *, level: str = "info") -> None:
    """在任务状态变更时同步写入可追溯时间线。"""
    db.add(
        TaskEvent(
            task_id=task.id,
            event=event,
            level=level,
            message=message,
            payload={"status": task.status},
        )
    )


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """校验确认卡后原子入队；未确认的非法字段不会产生任务行。"""
    _validate_session(db, body.session_id, user.id)
    if body.session_id:
        existing = (
            db.query(Task)
            .filter(Task.session_id == body.session_id, Task.status.in_(ACTIVE_STATUSES))
            .first()
        )
        if existing:
            raise AppError(ErrorCode.VALIDATION, "会话已有未完成任务")

    if body.kind == "stress":
        parent = db.query(Task).filter(Task.id == body.parent_task_id).first()
        if not parent or parent.status != "succeeded":
            raise AppError(ErrorCode.VALIDATION, "压测父任务必须已成功")
        if parent.kind not in {"benchmark", "rag"}:
            raise AppError(ErrorCode.VALIDATION, "仅质量任务可派生压测")

    task = Task(
        kind=body.kind,
        session_id=body.session_id,
        parent_task_id=body.parent_task_id,
        config=body.snapshot(),
        progress={"done": 0, "total": 0, "message": "任务已入队"},
        created_by=user.id,
        status="queued",
    )
    db.add(task)
    db.flush()
    _append_event(db, task, "queued", "任务已入队")
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_create",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
            ip=request.client.host if request.client else None,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务") from None
    db.refresh(task)
    return _task_out(task)


@router.get("")
def list_tasks(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按状态和类型分页读取当前成员创建的任务。"""
    query = db.query(Task).filter(Task.created_by == user.id)
    if status:
        query = query.filter(Task.status == status)
    if kind:
        query = query.filter(Task.kind == kind)
    total = query.count()
    rows = query.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [_task_out(row) for row in rows], "total": total}


@router.get("/summary")
def task_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从真实任务表聚合当前成员近 24 小时的状态计数。"""
    rows = (
        db.query(Task.status, func.count(Task.id))
        .filter(Task.created_by == user.id)
        .group_by(Task.status)
        .all()
    )
    counts = {status: 0 for status in [*ACTIVE_STATUSES, *TERMINAL_STATUSES]}
    counts.update({status: count for status, count in rows})
    return {"status_counts": counts, "series": [], "diagnosis": []}


@router.get("/{task_id}", response_model=TaskDetailOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回任务配置快照和按时间排序的事件时间线。"""
    task = _owned_task(db, task_id, user.id)
    events = (
        db.query(TaskEvent)
        .filter(TaskEvent.task_id == task.id)
        .order_by(TaskEvent.ts, TaskEvent.id)
        .all()
    )
    payload = _task_out(task)
    payload["events"] = [TaskEventOut.model_validate(event).model_dump(mode="json") for event in events]
    return payload


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """取消非终态任务；M1 mock Worker 会在下一检查点停止。"""
    task = _owned_task(db, task_id, user.id)
    if task.status in TERMINAL_STATUSES:
        raise AppError(ErrorCode.VALIDATION, "任务已结束")
    task.cancel_requested_at = datetime.now(UTC)
    task.status = "cancelled"
    task.finished_at = task.cancel_requested_at
    task.progress = {**(task.progress or {}), "message": "任务已取消"}
    _append_event(db, task, "cancelled", "任务已取消")
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_cancel",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.post("/{task_id}/rerun", response_model=TaskOut, status_code=201)
def rerun_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """复制终态任务的确认卡快照，创建全新的 queued 任务。"""
    task = _owned_task(db, task_id, user.id)
    if task.status not in TERMINAL_STATUSES:
        raise AppError(ErrorCode.VALIDATION, "仅终态任务可重跑")
    if task.session_id:
        existing = (
            db.query(Task)
            .filter(Task.session_id == task.session_id, Task.status.in_(ACTIVE_STATUSES))
            .first()
        )
        if existing:
            raise AppError(ErrorCode.VALIDATION, "会话已有未完成任务")
    rerun = Task(
        kind=task.kind,
        session_id=task.session_id,
        parent_task_id=task.parent_task_id,
        config=dict(task.config),
        progress={"done": 0, "total": 0, "message": "重跑任务已入队"},
        created_by=user.id,
        status="queued",
    )
    db.add(rerun)
    db.flush()
    _append_event(db, rerun, "queued", "由历史任务复制并入队")
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_rerun",
            target_type="task",
            target_id=rerun.id,
            detail={"source_task_id": task.id},
            ip=request.client.host if request.client else None,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务") from None
    db.refresh(rerun)
    return _task_out(rerun)
