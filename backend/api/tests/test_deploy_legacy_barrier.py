"""在随机 PostgreSQL schema 验证旧 API 首次升级的真实表锁，不接触业务表。"""

import importlib.util
import io
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError


@pytest.fixture
def legacy_database():
    """仅在显式隔离测试库创建随机 schema，结束时只清理自身表。"""
    url = os.environ.get("LOOP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 LOOP_TEST_DATABASE_URL 指向隔离 PostgreSQL")
    schema = f"deploy_barrier_{uuid.uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as db:
            db.execute(text("CREATE TABLE agent_runtime_state (active_turn integer)"))
            db.execute(text("INSERT INTO agent_runtime_state VALUES (NULL)"))
            db.execute(text("CREATE TABLE agent_runs (status text)"))
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def load_barrier():
    """加载部署脚本中的实际实现，避免在测试内重写锁定算法。"""
    path = Path(__file__).resolve().parents[3] / "deploy/legacy_agent_barrier.py"
    spec = importlib.util.spec_from_file_location("legacy_agent_barrier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.hold_barrier


@pytest.mark.parametrize("statement", [
    "INSERT INTO agent_runtime_state VALUES (1)",
    "UPDATE agent_runtime_state SET active_turn = 1",
    "SELECT * FROM agent_runtime_state FOR UPDATE",
    "INSERT INTO agent_runs VALUES ('running')",
])
def test_barrier_blocks_competing_submission_until_released(legacy_database, statement):
    """空闲计数发出后新写入与行锁被实际阻挡；屏障释放后同一写入成功。"""
    output = io.StringIO()

    def competing_submission():
        """模拟宿主已收到零计数但尚未停机时到达的新回合。"""
        assert output.getvalue() == "0\n"
        with legacy_database.begin() as db:
            assert db.execute(text("SELECT count(*) FROM agent_runtime_state")).scalar_one() == 1
        with pytest.raises(OperationalError) as error:
            with legacy_database.begin() as db:
                db.execute(text("SET LOCAL lock_timeout = '100ms'"))
                db.execute(text(statement))
        assert error.value.orig.pgcode == "55P03"
        return "\n"

    load_barrier()(legacy_database, SimpleNamespace(readline=competing_submission), output)
    with legacy_database.begin() as db:
        db.execute(text("SET LOCAL lock_timeout = '100ms'"))
        db.execute(text(statement))


@pytest.mark.parametrize("main_active,expert_status,expected", [
    (1, "succeeded", 1), (None, "running", 1), (None, "queued", 1), (1, "running", 2),
])
def test_active_main_and_experts_are_counted_without_changes(legacy_database, main_active, expert_status, expected):
    """已有主回合与专家运行均阻止停机，检查本身不修改任何状态。"""
    with legacy_database.begin() as db:
        db.execute(text("UPDATE agent_runtime_state SET active_turn = :active"), {"active": main_active})
        db.execute(text("INSERT INTO agent_runs VALUES (:status)"), {"status": expert_status})
    output = io.StringIO()
    load_barrier()(legacy_database, io.StringIO("\n"), output)
    assert output.getvalue() == f"{expected}\n"
    with legacy_database.begin() as db:
        assert db.execute(text("SELECT active_turn FROM agent_runtime_state")).scalar_one() == main_active
        assert db.execute(text("SELECT status FROM agent_runs")).scalar_one() == expert_status


def test_missing_runtime_table_never_reports_idle(legacy_database):
    """不支持的旧 schema 不得发送零计数，失败后释放已取得的表锁。"""
    with legacy_database.begin() as db:
        db.execute(text("DROP TABLE agent_runs"))
    output = io.StringIO()
    with pytest.raises(ProgrammingError):
        load_barrier()(legacy_database, io.StringIO("\n"), output)
    assert output.getvalue() == ""
    with legacy_database.begin() as db:
        db.execute(text("SET LOCAL lock_timeout = '100ms'"))
        db.execute(text("UPDATE agent_runtime_state SET active_turn = 1"))


def test_parent_channel_failure_releases_barrier(legacy_database):
    """父进程通信异常后不留下阻挡后续回合的数据库锁。"""
    def disconnected():
        """模拟部署父进程丢失输入管道。"""
        raise OSError("closed")

    with pytest.raises(OSError):
        load_barrier()(legacy_database, SimpleNamespace(readline=disconnected), io.StringIO())
    with legacy_database.begin() as db:
        db.execute(text("SET LOCAL lock_timeout = '100ms'"))
        db.execute(text("UPDATE agent_runtime_state SET active_turn = 1"))
