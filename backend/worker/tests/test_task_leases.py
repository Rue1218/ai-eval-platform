"""Worker 中断回收、租约续期和旧执行器终态隔离回归。"""

from datetime import timedelta
from threading import Event, current_thread

import pytest
from app import benchmark, stress, task_state, testcase
from app.models import Task, TaskEvent, utcnow


def _task(task_id, status="running", expires_at=None, owner="worker-1"):
    """构造已有任务，租约为空用于模拟旧版本升级后的中断任务。"""
    return Task(
        id=task_id, kind="testcase", status=status, created_by="owner",
        claimed_by_worker_id=owner, claim_expires_at=expires_at,
        config={"case_source": {"text": "登录需求"}}, progress={}, result={},
    )


def test_restart_recovery_fails_orphans_and_releases_running_slots(worker_db_factory):
    """过期和旧版无租约任务只失败一次，活动租约、待确认及既有终态保持不变。"""
    now = utcnow()
    with worker_db_factory() as db:
        db.add_all([
            _task("legacy"), _task("expired", expires_at=now - timedelta(seconds=1)),
            _task("live", expires_at=now + timedelta(minutes=5)),
            _task("cancelled", status="cancelled", expires_at=now - timedelta(seconds=1)),
            _task("awaiting", status="awaiting_case_confirm"),
        ])
        db.commit()
        assert task_state.recover_expired_task_leases(db) == 2
        assert db.query(Task).filter(Task.status == "running").count() == 1
        for task_id in ("legacy", "expired"):
            row = db.get(Task, task_id)
            assert row.status == "failed"
            assert row.result["error_code"] == "TIMEOUT"
            assert row.claimed_by_worker_id is None and row.claim_expires_at is None
        assert db.get(Task, "cancelled").status == "cancelled"
        assert db.get(Task, "awaiting").status == "awaiting_case_confirm"
        assert task_state.recover_expired_task_leases(db) == 0
        assert db.query(TaskEvent).count() == 2


@pytest.mark.parametrize("stop_fails", [False, True])
def test_expired_stress_stops_after_recovery_commit_without_blocking_other_tasks(
    worker_db_factory, monkeypatch, stop_fails,
):
    """外部压测停止放在提交后；停止失败也不撤销回收或影响其他任务释放槽位。"""
    with worker_db_factory() as db:
        stress_task = _task("stress", expires_at=utcnow() - timedelta(seconds=1))
        stress_task.kind = "stress"
        db.add_all([stress_task, _task("testcase")])
        db.commit()
    stopped = []

    def stop_engine(task_id):
        """独立会话能看到失败终态，证明网络停止操作未持有回收事务的行锁。"""
        with worker_db_factory() as observer:
            assert observer.get(Task, task_id).status == "failed"
            assert observer.get(Task, "testcase").status == "failed"
        stopped.append(task_id)
        if stop_fails:
            raise ConnectionError("local stop failure")

    monkeypatch.setattr(stress, "_stop_engine", stop_engine)
    with worker_db_factory() as db:
        assert task_state.recover_expired_task_leases(db) == 2
        assert db.query(Task).filter(Task.status == "running").count() == 0
        assert task_state.recover_expired_task_leases(db) == 0
        assert db.query(TaskEvent).count() == 2
        assert "已停止" not in db.get(Task, "stress").result["error_message"]
    assert stopped == ["stress"]


@pytest.mark.parametrize("changed", ["owner", "expired", "cancelled"])
def test_heartbeat_cannot_renew_lost_or_expired_claim(worker_db_factory, changed):
    """不同持有者、已过期或已取消的领取不能被迟到心跳复活。"""
    with worker_db_factory() as db:
        db.add(_task(
            "task", status="cancelled" if changed == "cancelled" else "running",
            expires_at=utcnow() + timedelta(seconds=-1 if changed == "expired" else 60),
            owner="other" if changed == "owner" else "worker-1",
        ))
        db.commit()
    assert task_state.renew_task_lease("task", "worker-1") is False
    with task_state.task_lease_heartbeat("task", "worker-1") as active:
        assert active is False


def test_independent_heartbeat_renews_during_blocked_execution(worker_db_factory, monkeypatch):
    """执行线程等待外部结果时，心跳通过另一 Session 和线程持续续租。"""
    before = utcnow() + timedelta(seconds=30)
    with worker_db_factory() as db:
        db.add(_task("task", expires_at=before))
        db.commit()
    seen = Event()
    caller = current_thread()
    original = task_state.renew_task_lease

    def observed_renew(task_id, worker_id):
        """只在后台线程的真实数据库续租成功后解除执行线程的等待。"""
        result = original(task_id, worker_id)
        if current_thread() is not caller and result:
            seen.set()
        return result

    monkeypatch.setattr(task_state, "renew_task_lease", observed_renew)
    monkeypatch.setattr(task_state, "TASK_HEARTBEAT_SECONDS", 0.01)
    with task_state.task_lease_heartbeat("task", "worker-1") as active:
        assert active is True
        assert seen.wait(timeout=5)
        with worker_db_factory() as db:
            deadline = db.get(Task, "task").claim_expires_at
            assert deadline.replace(tzinfo=before.tzinfo) > before
            assert task_state.recover_expired_task_leases(db) == 0


def test_initial_heartbeat_database_error_prevents_execution(monkeypatch):
    """领取后首次续租故障不能启动供应商调用，也不能使主轮询退出。"""
    def unavailable(_task_id, _worker_id):
        """模拟数据库短暂不可达，不创建真实连接。"""
        raise ConnectionError("local test")

    monkeypatch.setattr(task_state, "renew_task_lease", unavailable)
    with task_state.task_lease_heartbeat("task", "worker-1") as active:
        assert active is False


def test_expired_lease_stops_next_benchmark_batch_before_recovery(worker_db_factory):
    """心跳失效但扫描尚未运行时，旧执行器也不得继续消耗模型额度。"""
    with worker_db_factory() as db:
        db.add(_task("task", expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
        assert benchmark._is_cancelled(db, "task") is True
        assert db.get(Task, "task").status == "running"


def test_old_executor_cannot_overwrite_recovered_failure(worker_db_factory):
    """旧执行器持有的 running 对象在回收后不能创建结果或覆盖失败原因。"""
    with worker_db_factory() as db:
        db.add(_task("task", expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    with worker_db_factory() as stale:
        cached = stale.get(Task, "task")
        assert cached.status == "running"
        # 即使扫描尚未运行，过期执行器也没有终态写权限。
        assert task_state.claim_running_task_for_terminal_write(stale, "task") is None
        stale.rollback()
        with worker_db_factory() as recovery:
            assert task_state.recover_expired_task_leases(recovery) == 1
        testcase._fail(stale, cached, "UPSTREAM", "迟到的供应商异常")
        assert task_state.claim_running_task_for_terminal_write(stale, "task") is None
    with worker_db_factory() as db:
        assert db.get(Task, "task").result["error_code"] == "TIMEOUT"
        assert db.query(TaskEvent).count() == 1
