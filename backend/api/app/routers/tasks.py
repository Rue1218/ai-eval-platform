from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Task, User
from ..schemas import TaskCreate, TaskOut

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

VALID_KINDS = {"benchmark", "rag", "testcase", "stress"}
TERMINAL = {"succeeded", "failed", "cancelled"}


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.kind not in VALID_KINDS:
        raise AppError(ErrorCode.VALIDATION, "无效的 kind")
    task = Task(
        kind=body.kind,
        session_id=body.session_id,
        config=body.config,
        created_by=user.id,
        status="queued",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Task)
    if user.role != "admin":
        q = q.filter(Task.created_by == user.id)
    if status:
        q = q.filter(Task.status == status)
    if kind:
        q = q.filter(Task.kind == kind)
    return q.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    if user.role != "admin" and task.created_by != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事")
    return task


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    if user.role != "admin" and task.created_by != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事")
    if task.status in TERMINAL:
        raise AppError(ErrorCode.VALIDATION, "任务已结束")
    task.status = "cancelled"
    db.add(AuditLog(action="task_cancel", detail={"task_id": task.id, "by": user.id}))
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/rerun", response_model=TaskOut, status_code=201)
def rerun_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    new_task = Task(
        kind=task.kind,
        session_id=task.session_id,
        config=task.config,
        created_by=user.id,
        status="queued",
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task
