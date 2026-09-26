"""任务入队审查回归：真实 ORM 覆盖文件授权、重新会签与重跑配额。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, BigInteger, Integer, MetaData, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB, dialect
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.execution.task_tools import prepare_task_request
from app.harness.execution.worker_bridge import enqueue_long_task
from app.models import AuditLog, StoredFile, Task, TaskEvent, User, Workspace
from app.models import Session as AgentSession
from app.routers.tasks import create_task, rerun_task
from app.schemas import TaskCreate


@pytest.fixture
def task_db():
    """仅适配测试 DDL 的 JSONB、自增键和部分索引，使用真实 SQL 查询与事务。"""
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for model in (User, Workspace, AgentSession, StoredFile, Task, TaskEvent, AuditLog):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif isinstance(column.type, BigInteger):
                column.type = Integer()
        for index in table.indexes:
            predicate = index.dialect_options["postgresql"].get("where")
            if predicate is not None:
                index.dialect_options["sqlite"]["where"] = predicate
    metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        db.add_all([
            User(id="owner", username="owner", password_hash="unused"),
            User(id="other", username="other", password_hash="unused"),
            AgentSession(id="session", user_id="owner"),
            StoredFile(id="private-file", filename="requirements.md", storage_path="unused",
                       size_bytes=1, sha256="0" * 64, uploaded_by="owner"),
        ])
        db.commit()
        yield db
    engine.dispose()


def _request():
    """构造不接触网络的路由请求。"""
    return Request({"type": "http", "headers": []})


def _history(db, *, kind="testcase", config=None, session_id=None):
    """插入可重跑的历史任务，配置仅包含测试用数据。"""
    task = Task(id="history", created_by="owner", kind=kind, status="succeeded",
                session_id=session_id, config=config or {"case_source": {"text": "需求"}})
    db.add(task)
    db.commit()
    return task


def test_rest_testcase_rejects_foreign_file_before_enqueue(task_db):
    """已登录成员知道文件 ID 仍不能通过生成入口读取其他成员私有文档。"""
    body = TaskCreate(kind="testcase", case_source={"file_id": "private-file"})
    with pytest.raises(AppError) as error:
        create_task(body, _request(), task_db, task_db.get(User, "other"))
    assert error.value.code == ErrorCode.UNAUTHORIZED
    assert task_db.query(Task).count() == 0


def test_rest_testcase_accepts_own_file(task_db):
    """文件属主可正常创建用例生成任务。"""
    body = TaskCreate(kind="testcase", case_source={"file_id": "private-file"})
    result = create_task(body, _request(), task_db, task_db.get(User, "owner"))
    assert result["status"] == "queued"


def test_quota_lock_allows_parallel_user_foreign_key_references(task_db):
    """配额锁须互斥且兼容发布版本的用户外键，避免 User→Dataset 与反序死锁。"""
    statements = []

    def capture_lock(execute_state):
        """SQLite 验证实际发出的查询，PostgreSQL 方言校验行锁级别。"""
        statement = execute_state.statement
        if execute_state.is_select and statement._for_update_arg is not None:
            statements.append(str(statement.compile(dialect=dialect())))

    event.listen(task_db, "do_orm_execute", capture_lock)
    try:
        create_task(TaskCreate(kind="testcase", case_source={"text": "需求"}),
                    _request(), task_db, task_db.get(User, "owner"))
    finally:
        event.remove(task_db, "do_orm_execute", capture_lock)
    assert any("users" in statement and "FOR NO KEY UPDATE" in statement for statement in statements)


def test_rerun_rechecks_source_file_owner(task_db):
    """历史配置不能作为当前文件访问权限的凭证。"""
    task_db.get(StoredFile, "private-file").uploaded_by = "other"
    task = _history(task_db, config={"case_source": {"file_id": "private-file"}})
    with pytest.raises(AppError) as error:
        rerun_task(task.id, _request(), task_db, task_db.get(User, "owner"))
    assert error.value.code == ErrorCode.UNAUTHORIZED
    assert task_db.query(Task).count() == 1


def test_rerun_enforces_personal_active_task_quota(task_db, monkeypatch):
    """无会话历史任务也不能通过重复重跑绕过个人配额。"""
    monkeypatch.setattr(settings, "max_active_tasks_per_user", 1)
    task = _history(task_db)
    rerun_task(task.id, _request(), task_db, task_db.get(User, "owner"))
    with pytest.raises(AppError) as error:
        rerun_task(task.id, _request(), task_db, task_db.get(User, "owner"))
    assert error.value.code == ErrorCode.CONCURRENCY
    assert task_db.query(Task).filter(Task.status == "queued").count() == 1


def test_rerun_cannot_bypass_session_confirmation(task_db):
    """会话存在待确认卡时，历史重跑须与普通创建保持相同阻挡规则。"""
    task_db.get(AgentSession, "session").pending_confirm = {"id": "pending"}
    task = _history(task_db, session_id="session")
    with pytest.raises(AppError) as error:
        rerun_task(task.id, _request(), task_db, task_db.get(User, "owner"))
    assert error.value.code == ErrorCode.CONCURRENCY
    assert task_db.query(Task).count() == 1


def test_agent_preparation_requires_prod_stress_countersign(task_db):
    """创建者的业务确认不能替代生产压测的另一名成员会签。"""
    _history(task_db, kind="benchmark")
    kind, spec, parent = prepare_task_request(task_db, {
        "kind": "stress", "parent_task_id": "history",
        "stress": {"env": "prod", "qps": 1, "duration_s": 1},
    }, SimpleNamespace(session_id="session", user_id="owner"))
    assert kind == "stress" and parent == "history"
    assert spec.get("need_approval") is True
    assert "approved_by" not in spec


def test_enqueue_drops_supplied_prod_approval(task_db):
    """所有桥接入口创建的是新任务，不能继承输入快照里的会签状态。"""
    config = {"stress": {"env": "prod"}, "need_approval": False, "approved_by": "other"}
    task_id = enqueue_long_task(task_db, "session", "owner", "stress", config)
    created = task_db.get(Task, task_id)
    assert created.config["need_approval"] is True
    assert "approved_by" not in created.config
    assert config["approved_by"] == "other"


@pytest.mark.parametrize("env,needs_approval", [("prod", True), ("test", False)])
def test_stress_rerun_does_not_reuse_historical_countersign(task_db, env, needs_approval):
    """生产重跑重新等待会签，测试环境重跑仍可直接排队。"""
    task = _history(task_db, kind="stress", config={
        "stress": {"env": env}, "need_approval": False, "approved_by": "other",
    })
    result = rerun_task(task.id, _request(), task_db, task_db.get(User, "owner"))
    created = task_db.get(Task, result["id"])
    assert created.config["need_approval"] is needs_approval
    assert "approved_by" not in created.config
    assert task.config["approved_by"] == "other"
