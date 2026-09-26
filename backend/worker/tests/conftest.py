"""Worker 持久化回归使用独立 SQLite 文件，不访问配置中的业务数据库。"""

import pytest
from app import main, stress, task_state, testcase
from app.models import CaseItem, CaseSet, ProtocolProfile, Setting, StoredFile, Task, TaskEvent
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _sqlite_json(_type, _compiler, **_kwargs):
    """仅为测试 DDL 把 PostgreSQL JSONB 映射到 SQLite JSON。"""
    return "JSON"


@compiles(BigInteger, "sqlite")
def _sqlite_integer(_type, _compiler, **_kwargs):
    """仅为测试 DDL 保留 SQLite 自增主键语义。"""
    return "INTEGER"


@pytest.fixture
def worker_db_factory(tmp_path, monkeypatch):
    """创建可跨线程访问的临时数据库；供应商和 WS 均不在夹具中调用。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    for model in (Task, TaskEvent, CaseSet, CaseItem, Setting, StoredFile, ProtocolProfile):
        model.__table__.create(engine)
    factory = sessionmaker(engine, autoflush=False)
    for module in (main, stress, task_state, testcase):
        monkeypatch.setattr(module, "SessionLocal", factory)
        monkeypatch.setattr(module, "push_ws", lambda *_args, **_kwargs: None)
    try:
        yield factory
    finally:
        engine.dispose()
