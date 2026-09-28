"""保留旧执行器调用入口；平台停用压测后不再派生子任务。"""

from sqlalchemy.orm import Session

from .models import Task


def maybe_spawn_stress(db: Session, parent: Task) -> Task | None:
    """旧评测完成时不再创建压测，历史父子任务仅供查询。"""
    return None
