"""Worker 终态写入的并发安全助手。"""

from sqlalchemy.orm import Session

from .models import Task

# 取消传播（P4-2）：worker 执行中轮询的终态集合
_TERMINATED = {"cancelled", "failed"}


def is_cancelled(db: Session, task_id: str) -> bool:
    """任务是否已进入取消/失败终态；worker 在 LLM 循环内轮询用。

    api 侧 task.cancel 会把状态置 ``cancelled``；执行器在下一步骤前检查，
    提前停止不烧 token，且不会覆盖终态（终态写入另有行锁保护）。
    """
    row = db.query(Task.status).filter(Task.id == task_id).first()
    return bool(row) and row[0] in _TERMINATED


def claim_running_task_for_terminal_write(db: Session, task_id: str) -> Task | None:
    """锁定并刷新运行中任务，确保取消不会被任一终态写入覆盖。

    取消请求若先提交，本函数会读到 ``cancelled`` 并返回 ``None``；若本函数
    先取得行锁，则完成写入先提交，随后取消接口按终态拒绝，二者形成明确顺序。
    """
    db.expire_all()
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if not task or task.status != "running":
        return None
    return task
