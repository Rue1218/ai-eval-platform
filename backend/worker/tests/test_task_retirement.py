"""平台转为用例生成后的旧任务取消和领取门禁。"""

from contextlib import contextmanager
from datetime import timedelta

import pytest
from app import main, stress, task_state
from app.models import Task, TaskEvent, utcnow


def _task(task_id, kind, status):
    """构造待切换的历史任务，运行态携带有效租约。"""
    return Task(
        id=task_id,
        kind=kind,
        status=status,
        created_by="owner",
        config={},
        progress={},
        result={},
        claimed_by_worker_id="old-worker" if status == "running" else None,
        claim_expires_at=utcnow() + timedelta(minutes=5) if status == "running" else None,
    )


def test_cancel_non_testcase_tasks_is_idempotent_and_stops_running_stress(
    worker_db_factory, monkeypatch,
):
    """只取消未结束旧任务；提交终态后才请求停止正在运行的外部压测。"""
    with worker_db_factory() as db:
        db.add_all([
            _task("benchmark-queued", "benchmark", "queued"),
            _task("rag-running", "rag", "running"),
            _task("stress-running", "stress", "running"),
            _task("stress-queued", "stress", "queued"),
            _task("testcase-queued", "testcase", "queued"),
            _task("testcase-running", "testcase", "running"),
            _task("benchmark-done", "benchmark", "succeeded"),
        ])
        db.commit()
    stopped = []

    def stop_engine(task_id):
        """停止网络调用时数据库锁已释放，其他会话可见取消终态。"""
        with worker_db_factory() as observer:
            assert observer.get(Task, task_id).status == "cancelled"
        stopped.append(task_id)

    monkeypatch.setattr(stress, "_stop_engine", stop_engine)
    with worker_db_factory() as db:
        assert task_state.cancel_non_testcase_tasks(db) == 4
        assert task_state.cancel_non_testcase_tasks(db) == 0
        assert db.query(TaskEvent).filter(TaskEvent.event == "cancelled").count() == 4
        for task_id in ("benchmark-queued", "rag-running", "stress-running", "stress-queued"):
            task = db.get(Task, task_id)
            assert task.status == "cancelled"
            assert task.cancel_requested_at and task.finished_at
            assert task.claimed_by_worker_id is None and task.claim_expires_at is None
        assert db.get(Task, "testcase-queued").status == "queued"
        assert db.get(Task, "testcase-running").status == "running"
        assert db.get(Task, "benchmark-done").status == "succeeded"
    assert stopped == ["stress-running"]


def test_worker_only_claims_testcase_even_before_legacy_cleanup(worker_db_factory, monkeypatch):
    """领取条件独立于清理器，防止旧任务在切换窗口被再次执行。"""
    with worker_db_factory() as db:
        db.add_all([
            _task("legacy-first", "benchmark", "queued"),
            _task("testcase-second", "testcase", "queued"),
        ])
        db.commit()
    monkeypatch.setattr(main, "cancel_non_testcase_tasks", lambda _db: 0)
    monkeypatch.setattr(main, "recover_expired_task_leases", lambda _db: 0)
    monkeypatch.setattr(main, "recover_expired_dataset_import_leases", lambda _db: 0)
    monkeypatch.setattr(main, "claim_next_dataset_import", lambda _db: None)
    monkeypatch.setattr(main, "_expire_stale_case_confirmations", lambda _db: 0)

    @contextmanager
    def active_lease(_task_id, _worker_id):
        """只验证领取选择，不启动真实续租线程。"""
        yield True

    executed = []
    monkeypatch.setattr(main, "task_lease_heartbeat", active_lease)
    monkeypatch.setattr(main, "_run_task", executed.append)
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: (_ for _ in ()).throw(StopIteration))
    with pytest.raises(StopIteration):
        main.loop()
    assert executed == ["testcase-second"]
    with worker_db_factory() as db:
        assert db.get(Task, "legacy-first").status == "queued"
        assert db.get(Task, "testcase-second").status == "running"


def test_cancelled_stress_cannot_write_progress_or_report(worker_db_factory, monkeypatch):
    """取消落库后，迟到的引擎状态不得覆盖终态或创建报告。"""
    with worker_db_factory() as db:
        db.add(_task("stress-task", "stress", "running"))
        db.commit()
    monkeypatch.setattr(stress, "resolve_job", lambda _db, _task: {"duration_s": 2})
    monkeypatch.setattr(stress, "_request_json", lambda *_args, **_kwargs: {"status": "running"})
    stopped = []
    monkeypatch.setattr(stress, "_stop_engine", stopped.append)

    def cancel_before_report(_status, *, sla_p99_ms):
        """模拟外部轮询返回后 Worker 清理器抢先提交取消。"""
        with worker_db_factory() as db:
            task = db.get(Task, "stress-task")
            task.status = "cancelled"
            task.progress = {"message": "评测与压测已停用，任务已取消"}
            db.commit()
        return {"qps": 1}

    monkeypatch.setattr(stress, "metrics_from_status", cancel_before_report)
    stress.run_stress("stress-task")
    with worker_db_factory() as db:
        task = db.get(Task, "stress-task")
        assert task.status == "cancelled"
        assert task.report_id is None
        assert task.progress["message"] == "评测与压测已停用，任务已取消"
    assert stopped == ["stress-task"]
