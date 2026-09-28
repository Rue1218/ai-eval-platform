"""任务与用例生成入口共用的来源授权、配额和新任务会签规则。"""

from typing import Any

from sqlalchemy.orm import Session

from .errors import AppError, ErrorCode
from .models import AuditLog, CaseSet, StoredFile, Task, User


def lock_owned_task_for_cancel(db: Session, task_id: str, user_id: str) -> Task:
    """先锁用例集、再锁任务；并发生成刚完成时重试以保持锁序。"""
    for _ in range(2):
        case_set = (
            db.query(CaseSet).filter(CaseSet.task_id == task_id)
            .populate_existing().with_for_update().first()
        )
        task = (
            db.query(Task).filter(Task.id == task_id)
            .populate_existing().with_for_update().first()
        )
        if not task:
            raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
        if task.created_by != user_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事")
        if task.status == "awaiting_case_confirm" and case_set is None:
            # 生成任务可能在首次查询后提交结果；释放 Task 锁后重按 CaseSet→Task 获取。
            db.rollback()
            continue
        if task.status == "awaiting_case_confirm" and case_set and case_set.status == "generated":
            case_set.status = "cancelled"
        if task.kind == "stress" and task.status == "running":
            # 外部压测引擎停发由 Worker 按此持久标记重试，API 只做快速取消。
            task.result = {**(task.result or {}), "stress_stop_pending": True}
        return task
    raise AppError(ErrorCode.CONCURRENCY, "用例集正在生成，请重试取消")


def require_owned_source_file(db: Session, file_id: str, user_id: str) -> StoredFile:
    """生成只能使用当前成员上传的文件，文件 ID 本身不代表访问授权。"""
    stored = db.get(StoredFile, file_id)
    if not stored or stored.uploaded_by != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "用例来源文件不存在或不属于当前成员")
    return stored


def prepare_new_task_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """只允许新建用例生成任务；历史评测配置仅供只读回放。"""
    assert_task_creation_allowed(kind)
    return dict(config)


def assert_task_creation_allowed(kind: str) -> None:
    """统一阻止新建或重跑已停用的评测与压测任务。"""
    if kind != "testcase":
        raise AppError(ErrorCode.VALIDATION, "平台仅支持新建测试用例生成任务")


def enforce_task_quota(db: Session, user_id: str, kind: str) -> None:
    """统一创建和重跑的配额门禁，拒绝审计由调用方决定是否提交。"""
    from .config import settings
    from .harness.execution.worker_bridge import count_active_tasks

    # NO KEY UPDATE 串行化配额计数，同时兼容其他资产写入用户外键时的 KEY SHARE。
    # 避免任务创建等待数据集锁、数据集发布等待用户外键锁形成循环。
    db.query(User).filter(User.id == user_id).with_for_update(key_share=True).first()
    if count_active_tasks(db, user_id=user_id) < settings.max_active_tasks_per_user:
        return
    db.add(AuditLog(user_id=user_id, action="task_quota_rejected", target_type="user",
                    target_id=user_id, detail={"kind": kind, "limit": settings.max_active_tasks_per_user}))
    raise AppError(ErrorCode.CONCURRENCY, "达到个人任务配额上限，请等待现有任务结束后再发起",
                   fields={"task_quota_rejected": True})
