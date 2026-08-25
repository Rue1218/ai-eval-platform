"""质量任务 succeeded 且 with_stress=true 时派生压测子任务（先评后压）。"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .events import push_ws
from .models import Task, TaskEvent

logger = logging.getLogger("worker.stress_spawn")


def maybe_spawn_stress(db: Session, parent: Task) -> Task | None:
    """父任务成功后按需插入 queued 的 stress 子任务；已派生则返回已有行。

    prod 环境写入 ``config.need_approval=true``，Worker 领取时跳过，等待会签。
    派生失败不得回滚父任务报告（质量结果已提交）。
    """
    if parent.kind not in {"benchmark", "rag"}:
        return None
    config = parent.config if isinstance(parent.config, dict) else {}
    if not config.get("with_stress"):
        return None
    existing = (
        db.query(Task)
        .filter(Task.parent_task_id == parent.id, Task.kind == "stress")
        .first()
    )
    if existing:
        return existing
    stress_cfg = config.get("stress")
    if not isinstance(stress_cfg, dict):
        logger.warning(
            "task %s with_stress=true 但缺少 stress 段，跳过派生",
            parent.id,
        )
        return None
    env = stress_cfg.get("env")
    need_approval = env == "prod"
    child = Task(
        kind="stress",
        status="queued",
        session_id=parent.session_id,
        parent_task_id=parent.id,
        created_by=parent.created_by,
        config={
            "parent_task_id": parent.id,
            "stress": stress_cfg,
            "need_approval": need_approval,
        },
        progress={
            "done": 0,
            "total": 0,
            "percent": 0,
            "message": "等待会签后发压" if need_approval else "压测已入队",
        },
    )
    db.add(child)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.warning("task %s 派生压测时会话仍有活动任务，跳过", parent.id)
        return None
    db.add(
        TaskEvent(
            task_id=child.id,
            event="queued",
            message="由质量任务派生压测",
            payload={"parent_task_id": parent.id, "need_approval": need_approval},
        )
    )
    db.commit()
    push_ws(
        child.session_id,
        "progress",
        {
            "percent": 0,
            "done": 0,
            "total": 0,
            "message": child.progress.get("message") if isinstance(child.progress, dict) else "压测已入队",
        },
        task_id=child.id,
    )
    logger.info(
        "spawned stress task %s from %s need_approval=%s",
        child.id,
        parent.id,
        need_approval,
    )
    return child
