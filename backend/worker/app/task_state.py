"""Worker 终态写入的并发安全助手。"""

from sqlalchemy.orm import Session

from .models import Task


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
