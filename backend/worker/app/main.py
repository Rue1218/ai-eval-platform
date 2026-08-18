import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Report, Task, TaskEvent, WsEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://aieval:aieval_pass@localhost:5432/aieval"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

TERMINAL = {"succeeded", "failed", "cancelled"}


def _push_ws(session_id: str | None, event: str, payload: dict) -> None:
    if not session_id:
        return
    db = SessionLocal()
    try:
        max_eid = (
            db.query(WsEvent.event_id)
            .filter(WsEvent.session_id == session_id)
            .order_by(WsEvent.event_id.desc())
            .first()
        )
        event_id = (max_eid[0] + 1) if max_eid else 1
        db.add(WsEvent(session_id=session_id, event_id=event_id, event=event, payload=payload))
        db.commit()
    finally:
        db.close()


def _run_task(task: Task) -> None:
    """骨架版执行器：mock 执行 2 秒后置 succeeded。

    后续按 kind 分发到真实执行器：
      benchmark  -> 三协议适配 + 规则评分
      rag        -> LightRAG / 外部 Chat RAG
      testcase   -> 用例生成（进入 awaiting_case_confirm）
      stress     -> 下发到 stress 容器（go-stress-testing）
    """
    db = SessionLocal()
    try:
        db.add(TaskEvent(task_id=task.id, event="start", payload={"kind": task.kind}))
        db.commit()

        _push_ws(task.session_id, "progress", {"task_id": task.id, "done": 0, "total": 1, "message": "执行中"})

        time.sleep(2)

        # 期间若被取消则停止
        db.refresh(task)
        if task.status == "cancelled":
            return

        report_id = None
        if task.kind in {"benchmark", "rag", "stress"}:
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

        _push_ws(task.session_id, "report", {"task_id": task.id, "report_id": report_id})
        logger.info("task %s (%s) succeeded", task.id, task.kind)
    except Exception:
        db.rollback()
        task.status = "failed"
        task.finished_at = datetime.now(timezone.utc)
        db.add(TaskEvent(task_id=task.id, event="error", payload={"message": "执行失败"}))
        db.commit()
        _push_ws(task.session_id, "error", {"task_id": task.id, "code": "INTERNAL", "message": "执行失败"})
        logger.exception("task %s failed", task.id)
    finally:
        db.close()


def loop() -> None:
    while True:
        db = SessionLocal()
        try:
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
                _run_task(task)
        except Exception:
            logger.exception("worker loop error")
        finally:
            db.close()
        time.sleep(1)


if __name__ == "__main__":
    logger.info("worker started, db=%s", DATABASE_URL)
    loop()
