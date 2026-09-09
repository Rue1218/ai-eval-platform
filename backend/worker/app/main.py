"""Worker 主循环：轮询 PG 任务队列并按 kind 分发执行器。

- ``benchmark`` / ``testcase``：真实执行器（见 benchmark.py / testcase.py）；
- ``rag``：真实执行器（见 rag.py：LightRAG 检索优先，本地关键词兜底）；
- ``stress``：下发 stress 容器发压，轮询取消并写 time_series 报告。

主循环同时承担 72h 用例确认超时扫描（PRD 3.3 / 5.4.1）：generated 状态的
用例集过期后联动 awaiting_case_confirm 任务与用例集双双置 cancelled。
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import not_

from .benchmark import run_benchmark
from .db import SessionLocal
from .dataset_import import (
    claim_next_dataset_import,
    recover_expired_dataset_import_leases,
    run_dataset_import,
)
from .events import push_ws
from .models import CaseSet, Setting, Task, TaskEvent
from .rag import run_rag
from .stress import run_stress
from .task_state import claim_running_task_for_terminal_write
from .testcase import run_testcase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

TERMINAL = {"succeeded", "failed", "cancelled"}

# 平台并发上限默认值（PRD 3.4 / 后端计划 W4）：与 api 侧 DEFAULT_SETTINGS 保持一致
DEFAULT_MAX_RUNNING_TASKS = 3

# 72h 超时扫描节流间隔（秒）：主循环 1s 一轮，扫描器每 60s 实际执行一次
EXPIRE_SCAN_INTERVAL_S = 60.0


def _max_running_tasks(db) -> int:
    """读取 settings.max_running_tasks 并发闸门；缺失或非法时回退默认 3。"""
    row = db.query(Setting).filter(Setting.key == "max_running_tasks").first()
    value = row.value if row else None
    if isinstance(value, bool):
        return DEFAULT_MAX_RUNNING_TASKS
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, float) and value >= 1:
        return int(value)
    return DEFAULT_MAX_RUNNING_TASKS


def _run_task(task_id: str) -> None:
    """按任务类型分发执行。

    入参为任务 ID 而非 ORM 对象：主循环 Session 与执行器 Session 相互独立，
    直接传递跨 Session 的 ORM 实例会导致 refresh 抛 InvalidRequestError、
    状态赋值不进脏检查（任务永久卡 running）。
    """
    db = SessionLocal()
    task: Task | None = None
    try:
        # 在本函数自己的 Session 内重新加载任务，确保后续读写均被脏检查追踪
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error("task %s not found, skip execution", task_id)
            return

        db.add(TaskEvent(task_id=task.id, event="start", payload={"kind": task.kind}))
        db.commit()
        logger.info("开始执行 task=%s kind=%s", task.id, task.kind)
        print(f"[worker] start task={task.id} kind={task.kind}", flush=True)

        if task.kind == "rag":
            # M3 真实执行：LightRAG 检索优先，本地关键词检索兜底；
            # 执行器自管数据库会话与任务终态，这里提前释放本层会话
            db.close()
            logger.info("task %s (rag) dispatch to real executor", task_id)
            run_rag(task_id)
            return

        if task.kind == "benchmark":
            # M2 真实执行：两类协议调用 + 规则评分 + 预算熔断 + 断点续跑；
            # 执行器自管数据库会话与任务终态，这里提前释放本层会话
            db.close()
            logger.info("task %s (benchmark) dispatch to real executor", task_id)
            run_benchmark(task_id)
            return

        if task.kind == "testcase":
            # M2 W8 真实执行：六策略 LLM 生成 + 自检红字 + awaiting_case_confirm；
            # 执行器自管数据库会话与任务状态流转
            db.close()
            logger.info("task %s (testcase) dispatch to real executor", task_id)
            run_testcase(task_id)
            return

        if task.kind == "stress":
            db.close()
            logger.info("task %s (stress) dispatch to stress engine", task_id)
            run_stress(task_id)
            return

        logger.error("task %s unknown kind=%s", task_id, task.kind)
        task = claim_running_task_for_terminal_write(db, task_id)
        if not task:
            return
        task.status = "failed"
        task.finished_at = datetime.now(timezone.utc)
        db.add(
            TaskEvent(
                task_id=task.id,
                event="error",
                payload={"message": "未知任务类型"},
            )
        )
        db.commit()
        push_ws(
            task.session_id,
            "error",
            {"code": "VALIDATION", "message": "未知任务类型"},
            task_id=task.id,
        )
    except Exception as exc:
        db.rollback()
        # 详细堆栈只进服务端日志;给浏览器/事件流的失败原因仅透出异常类名辅助定位
        logger.exception("task %s execution error", task_id)
        print(f"[worker] failed task={task_id}", flush=True)
        # 失败状态落库单独保护：即使落库再失败也不阻断 error 事件推送
        try:
            if task is not None:
                task = claim_running_task_for_terminal_write(db, task.id)
                if not task:
                    logger.info("task %s skipped exception failure because it is no longer running", task_id)
                    return
                task.status = "failed"
                task.finished_at = datetime.now(timezone.utc)
            db.add(
                TaskEvent(
                    task_id=task_id,
                    event="error",
                    payload={"message": f"执行失败({type(exc).__name__})"},
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("task %s failed-status persist error", task_id)
        push_ws(
            task.session_id if task is not None else None,
            "error",
            {"code": "INTERNAL", "message": f"执行失败({type(exc).__name__})"},
            task_id=task_id,
        )
    finally:
        db.close()


def _expire_stale_case_confirmations(db) -> int:
    """72h 用例确认超时扫描（PRD 3.3 / 5.4.1）。

    generated 状态且 ``expires_at`` 已过期的用例集 → cancelled；关联任务仍在
    ``awaiting_case_confirm`` 时同步取消并推送 WS 事件。任务已被单独取消的
    悬挂用例集也一并清理（扫描器只改 case set / task 状态，不动其它域）。
    返回本次取消的用例集数量，供日志与测试观测。
    """
    now = datetime.now(timezone.utc)
    stale = (
        db.query(CaseSet)
        .filter(
            CaseSet.status == "generated",
            CaseSet.expires_at.isnot(None),
            CaseSet.expires_at < now,
        )
        .all()
    )
    if not stale:
        return 0
    for case_set in stale:
        case_set.status = "cancelled"
        if not case_set.task_id:
            continue
        task = (
            db.query(Task)
            .filter(Task.id == case_set.task_id, Task.status == "awaiting_case_confirm")
            .first()
        )
        if task:
            task.status = "cancelled"
            task.finished_at = now
            task.progress = {**(task.progress or {}), "message": "用例确认超时，任务已自动取消"}
            db.add(
                TaskEvent(
                    task_id=task.id,
                    event="cancelled",
                    message="用例确认超过 72h，任务自动取消",
                    payload={"case_set_id": case_set.id},
                )
            )
    db.commit()
    # 推送放事务外：批量加载关联任务后逐个通知，避免逐条查询造成 N+1
    task_ids = [case_set.task_id for case_set in stale if case_set.task_id]
    tasks_by_id = {task.id: task for task in db.query(Task).filter(Task.id.in_(task_ids)).all()}
    for case_set in stale:
        task = tasks_by_id.get(case_set.task_id)
        if task and task.session_id:
            push_ws(
                task.session_id,
                "progress",
                {"percent": 100, "done": 1, "total": 1, "message": "用例确认超时，任务已自动取消"},
                task_id=task.id,
            )
    logger.info("expired %d stale case set(s)", len(stale))
    return len(stale)


def loop() -> None:
    """轮询评测与导入两条独立队列，二者各自受并发闸门和租约约束。"""
    last_expire_scan = 0.0
    while True:
        db = SessionLocal()
        task_id: str | None = None
        import_claim: tuple[str, str] | None = None
        try:
            # 导入租约独立于 Task；先回收异常退出的领取，再按设置尝试领取一个作业。
            recover_expired_dataset_import_leases(db)
            import_claim = claim_next_dataset_import(db)
            # 平台并发闸门（PRD 3.4）：running 任务达到 max_running_tasks 时
            # 不领取新任务，queued 任务保持排队；会话内串行由 tasks 表的
            # 部分唯一索引 uq_tasks_active_session 在创建侧保证。
            running = db.query(Task).filter(Task.status == "running").count()
            if not import_claim and running < _max_running_tasks(db):
                task = (
                    db.query(Task)
                    .filter(Task.status == "queued")
                    .filter(not_(Task.config.contains({"need_approval": True})))
                    .order_by(Task.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .first()
                )
                if task:
                    task.status = "running"
                    task.started_at = datetime.now(timezone.utc)
                    db.commit()
                    task_id = task.id
        except Exception:
            logger.exception("worker loop error")
        finally:
            db.close()
        # 执行器自建 Session；主循环绝不将 ORM 实体跨 Session 传递。
        if import_claim:
            import_id, lease_token = import_claim
            logger.info("开始执行 dataset import=%s", import_id)
            print(f"[worker] dataset-import start import={import_id}", flush=True)
            run_dataset_import(import_id, lease_token)
        elif task_id:
            _run_task(task_id)
        # 72h 超时扫描：节流执行，避免每秒全表扫（表量级小，代价可忽略）
        if time.monotonic() - last_expire_scan >= EXPIRE_SCAN_INTERVAL_S:
            last_expire_scan = time.monotonic()
            scan_db = SessionLocal()
            try:
                _expire_stale_case_confirmations(scan_db)
            except Exception:
                scan_db.rollback()
                logger.exception("case confirmation expire scan error")
            finally:
                scan_db.close()
        time.sleep(1)


if __name__ == "__main__":
    logger.info("worker started")
    print("[worker] started", flush=True)
    loop()
