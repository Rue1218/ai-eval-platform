"""Worker 任务租约、取消检查与终态写入的并发安全助手。"""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .db import SessionLocal
from .events import push_ws
from .models import Task, TaskEvent

logger = logging.getLogger("worker.task_state")

# 独立心跳覆盖阻塞模型调用；租约失效只失败收尾，绝不自动重复供应商调用。
TASK_LEASE_SECONDS = 120
TASK_HEARTBEAT_SECONDS = 30

# 取消传播（P4-2）：worker 执行中轮询的终态集合
_TERMINATED = {"cancelled", "failed"}


def cancel_non_testcase_tasks(db: Session) -> int:
    """停用评测后取消尚未结束的旧任务，提交后停止正在发压的引擎。"""
    now = datetime.now(UTC)
    rows = (
        db.query(Task)
        .filter(Task.kind != "testcase", Task.status.in_(("queued", "running")))
        .with_for_update(skip_locked=True)
        .populate_existing()
        .all()
    )
    cancelled: list[tuple[str, str | None, str, bool]] = []
    message = "评测与压测已停用，任务已取消"
    for task in rows:
        if task.status not in {"queued", "running"}:
            continue
        was_running = task.status == "running"
        task.status = "cancelled"
        task.cancel_requested_at = now
        task.finished_at = now
        task.claimed_by_worker_id = None
        task.claim_expires_at = None
        task.progress = {**(task.progress or {}), "message": message}
        db.add(TaskEvent(task_id=task.id, event="cancelled", message=message,
                         payload={"status": "cancelled"}))
        cancelled.append((task.id, task.session_id, task.kind, was_running))
    db.commit()
    for task_id, session_id, kind, was_running in cancelled:
        if kind == "stress" and was_running:
            from .stress import _stop_engine

            _stop_engine(task_id)
        push_ws(session_id, "task_cancelled", {"status": "cancelled", "kind": kind}, task_id=task_id)
    return len(cancelled)


def lease_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    """判断已有租约是否过期；兼容本地 SQLite 返回无时区的 UTC 时间。"""
    if expires_at is None:
        return False
    expires_at = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
    return expires_at <= (now or datetime.now(UTC))


def renew_task_lease(task_id: str, worker_id: str) -> bool:
    """独立事务续租，仅允许当前持有者续租尚未过期的 running 任务。"""
    now = datetime.now(UTC)
    with SessionLocal() as db:
        updated = (
            db.query(Task)
            .filter(
                Task.id == task_id,
                Task.status == "running",
                Task.claimed_by_worker_id == worker_id,
                Task.claim_expires_at > now,
            )
            .update(
                {Task.claim_expires_at: now + timedelta(seconds=TASK_LEASE_SECONDS)},
                synchronize_session=False,
            )
        )
        db.commit()
        return updated == 1


@contextmanager
def task_lease_heartbeat(task_id: str, worker_id: str):
    """执行期间在独立线程续租；返回 False 时不得开始执行已经失效的领取。"""
    try:
        active = renew_task_lease(task_id, worker_id)
    except Exception:
        logger.warning("task lease initial renewal failed task=%s", task_id)
        active = False
    if not active:
        yield False
        return
    stopped = Event()

    def heartbeat() -> None:
        """阻塞调用不占用心跳线程；短暂数据库故障允许在有效期内重试。"""
        while not stopped.wait(TASK_HEARTBEAT_SECONDS):
            try:
                if not renew_task_lease(task_id, worker_id):
                    return
            except Exception:
                logger.warning("task lease heartbeat failed task=%s", task_id)

    thread = Thread(target=heartbeat, name=f"task-lease-{task_id[:8]}", daemon=True)
    thread.start()
    try:
        yield True
    finally:
        stopped.set()
        thread.join(timeout=1)


def recover_expired_task_leases(db: Session) -> int:
    """将中断的任务明确失败并释放槽位，兼容升级前没有租约的 running 行。"""
    now = datetime.now(UTC)
    rows = (
        db.query(Task)
        .filter(
            Task.status == "running",
            or_(Task.claim_expires_at.is_(None), Task.claim_expires_at <= now),
        )
        .with_for_update(skip_locked=True)
        .populate_existing()
        .all()
    )
    expired: list[tuple[str, str | None, str]] = []
    message = "任务执行失联或租约超时，已标记失败；请核查外部执行结果后手动重跑"
    for task in rows:
        # 获取锁之前心跳或终态可能已经提交，必须依据刷新后的行重新判定。
        if task.status != "running" or (
            task.claim_expires_at is not None and not lease_expired(task.claim_expires_at, now)
        ):
            continue
        task.status = "failed"
        task.finished_at = now
        task.claimed_by_worker_id = None
        task.claim_expires_at = None
        task.result = {**(task.result or {}), "error_code": "TIMEOUT", "error_message": message}
        task.progress = {**(task.progress or {}), "message": message}
        db.add(TaskEvent(task_id=task.id, event="error", level="error", message=message, payload={"code": "TIMEOUT"}))
        expired.append((task.id, task.session_id, task.kind))
    db.commit()
    for task_id, session_id, kind in expired:
        if kind == "stress":
            # 外部引擎可能仍在发压，提交回收后尽力停止，网络故障不能阻塞槽位释放。
            from .stress import _stop_engine

            try:
                _stop_engine(task_id)
            except Exception:
                logger.warning("expired stress stop failed task=%s", task_id)
        push_ws(session_id, "error", {"code": "TIMEOUT", "message": message}, task_id=task_id)
    return len(expired)


def is_cancelled(db: Session, task_id: str) -> bool:
    """任务是否已进入取消/失败终态；worker 在 LLM 循环内轮询用。

    api 侧 task.cancel 会把状态置 ``cancelled``；执行器在下一步骤前检查，
    提前停止不烧 token，且不会覆盖终态（终态写入另有行锁保护）。
    """
    row = db.query(Task.status, Task.claim_expires_at).filter(Task.id == task_id).first()
    return bool(row) and (row[0] in _TERMINATED or lease_expired(row[1]))


def claim_running_task_for_terminal_write(db: Session, task_id: str) -> Task | None:
    """锁定并刷新运行中任务，确保取消不会被任一终态写入覆盖。

    取消请求若先提交，本函数会读到 ``cancelled`` 并返回 ``None``；若本函数
    先取得行锁，则完成写入先提交，随后取消接口按终态拒绝，二者形成明确顺序。
    """
    db.expire_all()
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if not task or task.status != "running" or lease_expired(task.claim_expires_at):
        return None
    return task
