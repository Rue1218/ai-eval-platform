"""Worker 主循环：轮询 PG 任务队列并按 kind 分发执行器。

- ``benchmark``：M2 起走真实执行器（三协议调用 + 规则评分，见 benchmark.py）；
- ``rag`` / ``testcase`` / ``stress``：仍为骨架 mock（M3/M4 替换为真实实现），
  与真实执行保持同一领取入口，替换时不动本文件的分发结构。
"""

import logging
import time
from datetime import datetime, timezone

from .benchmark import run_benchmark
from .db import DATABASE_URL, SessionLocal
from .events import push_ws
from .models import Report, Setting, Task, TaskEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

TERMINAL = {"succeeded", "failed", "cancelled"}

# 平台并发上限默认值（PRD 3.4 / 后端计划 W4）：与 api 侧 DEFAULT_SETTINGS 保持一致
DEFAULT_MAX_RUNNING_TASKS = 3


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

        if task.kind == "benchmark":
            # M2 起真实执行：三协议调用 + 规则评分 + 预算熔断 + 断点续跑；
            # 执行器自管数据库会话与任务终态，这里提前释放本层会话
            db.close()
            logger.info("task %s (benchmark) dispatch to real executor", task_id)
            run_benchmark(task_id)
            return

        # ─── 以下为骨架 mock 流程（rag / testcase / stress，M3/M4 替换） ───
        time.sleep(2)

        # 期间若被取消则停止
        db.refresh(task)
        if task.status == "cancelled":
            return

        report_id = None
        if task.kind in {"rag", "stress"}:
            report = Report(task_id=task.id, kind=task.kind, metrics={"mock": True})
            db.add(report)
            db.flush()
            report_id = report.id

        task.status = "succeeded"
        task.finished_at = datetime.now(timezone.utc)
        task.report_id = report_id
        task.result = {"mock": True, "kind": task.kind}
        db.add(TaskEvent(task_id=task.id, event="finish", payload={"status": "succeeded"}))
        db.commit()

        push_ws(task.session_id, "progress", {"percent": 100, "done": 1, "total": 1, "message": "任务已完成"}, task_id=task.id)
        if report_id:
            push_ws(task.session_id, "report", {"report_id": report_id}, task_id=task.id)
        else:
            # testcase 等无报告类型：不允许推送空 report_id（前端会据此跳转 /reports/undefined）
            push_ws(task.session_id, "thought", {"text": "任务已完成（succeeded）。用例生成类任务请到「用例」页确认入库。"}, task_id=task.id)
        logger.info("task %s (%s) succeeded (mock)", task.id, task.kind)
    except Exception as exc:
        db.rollback()
        # 详细堆栈只进服务端日志;给浏览器/事件流的失败原因仅透出异常类名辅助定位
        logger.exception("task %s execution error", task_id)
        # 失败状态落库单独保护：即使落库再失败也不阻断 error 事件推送
        try:
            if task is not None:
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


def loop() -> None:
    """轮询任务队列：受平台并发闸门约束，超限时 queued 任务保持排队。"""
    while True:
        db = SessionLocal()
        try:
            # 平台并发闸门（PRD 3.4）：running 任务达到 max_running_tasks 时
            # 不领取新任务，queued 任务保持排队；会话内串行由 tasks 表的
            # 部分唯一索引 uq_tasks_active_session 在创建侧保证。
            running = db.query(Task).filter(Task.status == "running").count()
            if running < _max_running_tasks(db):
                task = (
                    db.query(Task)
                    .filter(Task.status == "queued")
                    .order_by(Task.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .first()
                )
                if task:
                    task.status = "running"
                    task.started_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(task)
                    _run_task(task.id)
        except Exception:
            logger.exception("worker loop error")
        finally:
            db.close()
        time.sleep(1)


if __name__ == "__main__":
    logger.info("worker started, db=%s", DATABASE_URL)
    loop()
