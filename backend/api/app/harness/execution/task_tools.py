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


def _task_spec(arguments: Mapping[str, object], session_id: str):
    """按 REST 同一 TaskCreate 契约校验 MCP 入队参数。

    ``session_id`` 只能由平台上下文注入，禁止让模型覆盖；这样 MCP 桥与
    ``POST /api/tasks`` 对 benchmark、RAG、压测和用例生成使用同一份必填规则。
    """
    from pydantic import ValidationError

    from app.schemas import TaskCreate

    payload = dict(arguments)
    payload["session_id"] = session_id
    try:
        return TaskCreate.model_validate(payload)
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {}
        if first_error.get("type") == "literal_error":
            message = f"未知任务类型：{payload.get('kind') or ''}"
        else:
            message = str(first_error.get("msg") or "任务规格无效")
            # Pydantic 为模型级中文校验加上的英文前缀不应透传给浏览器。
            message = message.removeprefix("Value error, ")
        raise AppError(ErrorCode.VALIDATION, message) from None


def _context_ids(context: object) -> tuple[str, str]:
    """提取平台注入的 session_id/user_id；缺失即拒绝（模型不可伪造）。"""
    session_id = str(getattr(context, "session_id", "") or "")
    user_id = str(getattr(context, "user_id", "") or "")
    if not session_id or not user_id:
        raise AppError(ErrorCode.VALIDATION, "缺少工具上下文")
    return session_id, user_id


def prepare_task_request(db, arguments: Mapping[str, object], context: object) -> tuple[str, dict, str | None]:
    """校验并冻结 TaskSpec；不入队、不提交、不关闭调用方事务。

    主服务在确认前调用取得 spec，确认后同一入队事务再次调用并核对 spec_hash。
    pending_confirm 属于调用方的交互状态，本函数不会拒绝或消费当前确认卡。
    配额拒绝审计仅添加到当前事务，是否提交由外层决定。
    """
    from app.config import settings
    from app.harness.memory.episodic import get_active_tasks
    from app.models import AuditLog, Dataset, DatasetVersion, ProtocolProfile, StoredFile, Task
    from app.session_access import require_visible_session

    from .worker_bridge import count_active_tasks

    session_id, user_id = _context_ids(context)
    task_spec = _task_spec(arguments, session_id)
    kind = task_spec.kind
    if kind not in TASK_KINDS:
        raise AppError(ErrorCode.VALIDATION, f"未知任务类型：{kind}")
    require_visible_session(db, session_id, user_id, lock=True)
    if get_active_tasks(db, session_id):
        raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务")
    if count_active_tasks(db, user_id=user_id) >= settings.max_active_tasks_per_user:
        db.add(AuditLog(user_id=user_id, action="task_quota_rejected", target_type="user",
                        target_id=user_id, detail={"kind": kind, "limit": settings.max_active_tasks_per_user}))
        raise AppError(ErrorCode.CONCURRENCY, "达到个人任务配额上限，请等待现有任务结束后再发起",
                       fields={"task_quota_rejected": True})

    parent_task_id = task_spec.parent_task_id
    if parent_task_id:
        parent = db.get(Task, parent_task_id)
        if not parent:
            raise AppError(ErrorCode.VALIDATION, "压测任务须由已成功的质量任务派生")
        if parent.created_by != user_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "没有权限使用该父任务")
        if parent.session_id:
            require_visible_session(db, parent.session_id, user_id)
        if kind == "stress" and (parent.status != "succeeded" or parent.kind not in {"benchmark", "rag"}):
            raise AppError(ErrorCode.VALIDATION, "压测任务须由已成功的质量任务派生")

    # 协议档目录按平台“全员同权”口径共享；created_by 仅用于审计，不能把
    # 创建者字段误当作使用 ACL，否则 Agent 工具会与 REST 创建任务的行为分叉。
    # 凭据本身仍只由服务端的协议档受控环境变量读取，不回传给调用者。
    profile_ids = set(task_spec.profile_ids)
    if task_spec.run and task_spec.run.judge_profile_id:
        profile_ids.add(task_spec.run.judge_profile_id)
    for profile_id in sorted(profile_ids):
        profile = db.get(ProtocolProfile, profile_id)
        if not profile:
            raise AppError(ErrorCode.NOT_FOUND, "关联模型协议档不存在")
    if task_spec.case_source and task_spec.case_source.file_id:
        file = db.get(StoredFile, task_spec.case_source.file_id)
        if not file or file.uploaded_by != user_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "用例来源文件不存在或不属于当前成员")

    spec = task_spec.snapshot()
    if kind == "benchmark":
        # 复用原锁与版本冻结规则，保留旧数据集尚无发布版本时的既有兼容行为。
        dataset = db.query(Dataset).filter(Dataset.id == task_spec.dataset_id).with_for_update().first()
        if not dataset:
            raise AppError(ErrorCode.NOT_FOUND, "关联数据集不存在")
        if dataset.active_version_id:
            version = db.query(DatasetVersion).filter(
                DatasetVersion.id == dataset.active_version_id,
                DatasetVersion.dataset_id == dataset.id,
            ).first()
            if not version:
                raise AppError(ErrorCode.INTERNAL, "数据集当前版本异常，无法创建评测任务")
            spec["dataset_version_id"] = dataset.active_version_id
            spec["dataset_version_no"] = version.version_no
    spec.pop("parent_task_id", None)
    return kind, spec, parent_task_id


def create_task_safe(arguments: Mapping[str, object], context: object) -> dict:
    """保留旧自管事务入口：待确认卡阻挡，校验成功后直接入队，不等待 Worker。"""
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.session_access import require_visible_session

    session_id, user_id = _context_ids(context)
    # 维持原入口先校验参数、再打开数据库的错误顺序。
    _task_spec(arguments, session_id)
    db = SessionLocal()
    try:
        session = require_visible_session(db, session_id, user_id, lock=True)
        if session.pending_confirm:
            raise AppError(ErrorCode.CONCURRENCY, "会话存在待确认任务，请先确认或取消")
        try:
            kind, spec, parent_task_id = prepare_task_request(db, arguments, context)
        except AppError as exc:
            if (exc.fields or {}).get("task_quota_rejected"):
                # 旧入口保留配额拒绝审计的独立提交，新 helper 绝不自行 commit。
                db.commit()
            raise
        try:
            task_id = enqueue_long_task(db, session_id=session_id, user_id=user_id,
                                        kind=kind, spec=spec, parent_task_id=parent_task_id)
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
