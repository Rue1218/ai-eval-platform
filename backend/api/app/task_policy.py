"""任务与用例生成入口共用的来源授权、配额和新任务会签规则。"""

from typing import Any

from sqlalchemy.orm import Session

from .errors import AppError, ErrorCode
from .models import AuditLog, StoredFile, User


def require_owned_source_file(db: Session, file_id: str, user_id: str) -> StoredFile:
    """生成只能使用当前成员上传的文件，文件 ID 本身不代表访问授权。"""
    stored = db.get(StoredFile, file_id)
    if not stored or stored.uploaded_by != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "用例来源文件不存在或不属于当前成员")
    return stored


def prepare_new_task_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """复制新任务配置；生产压测必须重新会签，不继承历史任务的批准身份。"""
    snapshot = dict(config)
    if kind == "stress":
        snapshot.pop("approved_by", None)
        snapshot["need_approval"] = (snapshot.get("stress") or {}).get("env") == "prod"
    return snapshot


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
