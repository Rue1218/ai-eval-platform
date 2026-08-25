"""任务控制面：确认卡入队、状态读取、取消和重跑。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Report, Task, TaskEvent, User
from ..models import Session as AgentSession
from ..schemas import TaskCreate, TaskDetailOut, TaskEventOut, TaskOut
from ..session_access import require_visible_session

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
ACTIVE_STATUSES = {"queued", "running", "awaiting_case_confirm"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def _task_out(task: Task) -> dict:
    """将任务 ORM 对象统一转换为前端需要的公开字段。

    同步把 config 快照中的 dataset_id/kb_id 提升为顶层引用（API §3.10 列表
    item 契约），列表页无需解包 config 即可展示数据集 / 知识库归属。
    """
    payload = TaskOut.model_validate(task).model_dump(mode="json")
    config = task.config or {}
    if isinstance(config, dict):
        payload["dataset_id"] = config.get("dataset_id")
        payload["kb_id"] = config.get("kb_id")
    return payload


def _owned_task(db: Session, task_id: str, user_id: str) -> Task:
    """锁定当前成员创建的任务，串行化取消、重跑与 Worker 终态写入。"""
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    if task.created_by != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事")
    return task


def _visible_task(db: Session, task_id: str) -> Task:
    """按全员只读口径加载任务（API §3.10：详情全员可见，写操作仍走 _owned_task）。"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    return task


def _validate_session(
    db: Session,
    session_id: str | None,
    user_id: str,
    *,
    lock: bool = False,
) -> AgentSession | None:
    """确保任务挂载的 Agent 会话对当前成员可见且未软删除。"""
    if not session_id:
        return None
    return require_visible_session(db, session_id, user_id, lock=lock)


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
    session = _validate_session(db, body.session_id, user.id, lock=bool(body.session_id))
    if session and session.pending_confirm:
        # 团队协作时不得绕过确认卡直接从 REST 抢占会话活动任务。
        raise AppError(ErrorCode.CONCURRENCY, "会话存在待确认任务，请先由发起人确认或取消")
    if body.session_id:
        existing = (
            db.query(Task)
            .filter(Task.session_id == body.session_id, Task.status.in_(ACTIVE_STATUSES))
            .first()
        )
        if existing:
            raise AppError(ErrorCode.VALIDATION, "会话已有未完成任务")

    # P4-2 资源配额：每用户活动任务上限（与 MCP task.create 同一规则 + 审计）
    from app.config import settings
    from app.harness.execution.worker_bridge import count_active_tasks

    if count_active_tasks(db, user_id=user.id) >= settings.max_active_tasks_per_user:
        db.add(
            AuditLog(
                user_id=user.id,
                action="task_quota_rejected",
                target_type="user",
                target_id=user.id,
                detail={"kind": body.kind, "limit": settings.max_active_tasks_per_user},
            )
        )
        db.commit()
        raise AppError(ErrorCode.CONCURRENCY, "达到个人任务配额上限，请等待现有任务结束后再发起")

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
    """按状态和类型分页读取全员任务（API §3.10：列表全员可见，取消/重跑仍限创建者）。"""
    query = db.query(Task)
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
    """从真实任务表聚合全员任务状态计数（任务中心为团队共享视图）。"""
    rows = db.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
    counts = {status: 0 for status in [*ACTIVE_STATUSES, *TERMINAL_STATUSES]}
    counts.update({status: count for status, count in rows})
    return {"status_counts": counts, "series": [], "diagnosis": []}


@router.get("/{task_id}", response_model=TaskDetailOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回任务配置快照和按时间排序的事件时间线（全员只读）。"""
    task = _visible_task(db, task_id)
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
        # 已私有化或软删除的会话不能承接新任务，避免从任务页绕过会话边界。
        _validate_session(db, task.session_id, user.id)
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


@router.post("/{task_id}/approve-stress", response_model=TaskOut)
def approve_stress(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """会签放行压测任务：入参可为压测子任务或其质量父任务；prod 发压须非创建者会签。"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    # 解析到对应的 kind=stress 子任务（先评后压由 Worker 派生）
    stress = task
    if task.kind != "stress":
        stress = (
            db.query(Task)
            .filter(Task.parent_task_id == task.id, Task.kind == "stress")
            .order_by(Task.created_at.asc())
            .first()
        )
    if not stress:
        raise AppError(ErrorCode.NOT_FOUND, "未找到关联的压测任务")
    if stress.status in TERMINAL_STATUSES:
        raise AppError(ErrorCode.VALIDATION, "压测任务已结束")

    config = dict(stress.config or {})
    env = (config.get("stress") or {}).get("env")
    if env == "prod" and stress.created_by == user.id:
        # prod 会签人必须不是创建者本人
        raise AppError(ErrorCode.NEED_APPROVAL, "prod 发压须由非创建者的成员会签")
    config["need_approval"] = False
    config["approved_by"] = user.id
    stress.config = config
    _append_event(db, stress, "approved", f"压测会签通过（{user.username}）")
    db.add(
        AuditLog(
            user_id=user.id,
            action="prod_approve",
            target_type="task",
            target_id=stress.id,
            detail={"env": env, "parent_task_id": stress.parent_task_id},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    db.refresh(stress)
    return _task_out(stress)


@router.get("/{task_id}/stress-series")
def stress_series(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """压测时序曲线：取报告 metrics.time_series 映射为契约 points；无数据返回空数组。"""
    task = db.query(Task).filter(Task.id == task_id, Task.kind == "stress").first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "压测任务不存在")
    report = db.query(Report).filter(Report.task_id == task.id).first()
    points: list[dict] = []
    series = (report.metrics or {}).get("time_series") if report else None
    if isinstance(series, list):
        for point in series:
            if isinstance(point, dict):
                points.append(
                    {
                        "ts": point.get("ts"),
                        "qps": point.get("qps"),
                        "rt_ms": point.get("rt_ms"),
                        "error_rate": point.get("error_rate"),
                    }
                )
    return {"task_id": task.id, "points": points}
