"""真实隔离 PostgreSQL 验证偏好事务与并发；不读取默认生产数据库配置。"""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import delete, select, text

from app.harness.execution.worker_bridge import enqueue_long_task
from app.harness.memory.preference import prepare_private_prefs, read_prefs, write_prefs
from app.models import AuditLog, Session, Setting, Task
from tests import test_loop_store_pg as store_fixtures

pg_case = store_fixtures.pg_case


@pytest.fixture
def prefs_case(pg_case):
    """优先清理本例偏好和审计，之后由原夹具清理自身任务、会话和用户。"""
    try:
        yield pg_case
    finally:
        with pg_case.factory.begin() as db:
            db.execute(delete(Setting).where(Setting.key == f"agent_prefs:{pg_case.user_id}"))
            db.execute(delete(AuditLog).where(AuditLog.user_id == pg_case.user_id))


@pytest.mark.parametrize("fail_fact", [False, True])
def test_pg_task_preferences_and_receipt_commit_atomically(prefs_case, fail_fact):
    """任务、偏好和事实同事务；事实写入故障不得留下偏好或已入队任务。"""
    with prefs_case.log() as log:
        try:
            with log._transaction() as (db, session, state):
                task_id = enqueue_long_task(db, session.id, prefs_case.user_id, "testcase", {}, commit=False)
                write_prefs(db, prefs_case.user_id, {"last_kind": "testcase"}, commit=False)
                log._append(db, session, state, "task/queued", {
                    "turn": 1, "step": 1, "attempt_id": "prefs", "call_id": "create",
                    "task_id": task_id, "content": "queued",
                })
                if fail_fact:
                    raise RuntimeError("模拟确认事实事务失败")
        except RuntimeError as exc:
            assert fail_fact and str(exc) == "模拟确认事实事务失败"
        with prefs_case.factory() as db:
            tasks = list(db.scalars(select(Task).where(Task.session_id == log.session_id)))
            prefs = read_prefs(db, prefs_case.user_id)
        assert bool(tasks) is (not fail_fact)
        assert bool(prefs) is (not fail_fact)
        assert bool(log.read()) is (not fail_fact)


def test_pg_first_preferences_from_parallel_sessions_do_not_fail_enqueue(prefs_case):
    """两会话首次确认共享同一偏好键，等待用户锁后更新而非唯一键冲突。"""
    first_session, second_session = prefs_case.session(), prefs_case.session()
    ready = Queue()

    def second_enqueue():
        """第二事务先创建任务，以真实外键 KEY SHARE 检验偏好锁兼容性。"""
        with prefs_case.factory.begin() as db:
            db.execute(select(Session.id).where(Session.id == second_session).with_for_update())
            task_id = enqueue_long_task(db, second_session, prefs_case.user_id, "testcase", {}, commit=False)
            ready.put(db.scalar(text("SELECT pg_backend_pid()")))
            write_prefs(db, prefs_case.user_id, {"last_kind": "rag"}, commit=False)
            return task_id

    with prefs_case.factory() as first, ThreadPoolExecutor(max_workers=1) as executor:
        first.execute(select(Session.id).where(Session.id == first_session).with_for_update())
        first_pid = first.scalar(text("SELECT pg_backend_pid()"))
        enqueue_long_task(first, first_session, prefs_case.user_id, "testcase", {}, commit=False)
        write_prefs(first, prefs_case.user_id, {"last_kind": "benchmark"}, commit=False)
        first.flush()
        future = executor.submit(second_enqueue)
        try:
            second_pid = ready.get(timeout=5)
            deadline = monotonic() + 5
            with prefs_case.factory() as observer:
                while first_pid not in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid}):
                    assert monotonic() < deadline, "第二偏好写入没有等待首事务"
                    Event().wait(0.01)
            # 以数据库阻塞关系为同步条件，不依靠固定 sleep 猜测两个事务是否重叠。
            assert not future.done()
            first.commit()
            assert future.result(timeout=5)
        finally:
            first.rollback()
    with prefs_case.factory() as db:
        assert len(list(db.scalars(select(Task).where(Task.session_id.in_([first_session, second_session]))))) == 2
        assert read_prefs(db, prefs_case.user_id)["last_kind"] == "rag"


def test_pg_preference_lock_refreshes_old_private_identity(prefs_case):
    """旧身份映射不能覆盖锁后已共享的最新状态，避免共享后注入个人数据。"""
    session_id = prefs_case.session()
    with prefs_case.factory() as db:
        write_prefs(db, prefs_case.user_id, {"last_kind": "rag"})
        old_session = db.get(Session, session_id)
        assert old_session.visibility == "private"
        with prefs_case.factory.begin() as other:
            row = other.get(Session, session_id)
            row.visibility = "team"
        assert prepare_private_prefs(db, session_id, prefs_case.user_id) == {}
        assert old_session.visibility == "team"
