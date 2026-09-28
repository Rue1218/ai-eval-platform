"""新部署不再伪造评测结果，同时保留原有历史任务。"""

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    CaseFolder,
    CaseItem,
    CaseSet,
    Dataset,
    DatasetFolder,
    DatasetRow,
    DispatchEvent,
    DispatchWorker,
    GoldQa,
    GoldQaItem,
    KnowledgeBase,
    ProtocolProfile,
    Report,
    Setting,
    Task,
    TaskEvent,
    User,
)
from app.seed import bootstrap_preview_data


@compiles(JSONB, "sqlite")
def _sqlite_json(_type, _compiler, **_kwargs):
    """让预览播种测试在临时 SQLite 中创建 PostgreSQL JSONB 列。"""
    return "JSON"


@compiles(BigInteger, "sqlite")
def _sqlite_integer(_type, _compiler, **_kwargs):
    """保持测试中的事件表主键可自增。"""
    return "INTEGER"


def test_preview_seed_does_not_forge_evaluation_and_keeps_history():
    """空库不生成假成功报告；已有真实历史任务在重启播种后原样保留。"""
    engine = create_engine("sqlite:///:memory:")
    tables = [
        User, ProtocolProfile, Setting, DatasetFolder, Dataset, DatasetRow,
        CaseFolder, CaseSet, CaseItem, KnowledgeBase, GoldQa, GoldQaItem,
        DispatchWorker, Task, Report, TaskEvent, DispatchEvent,
    ]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    db_factory = sessionmaker(engine)
    try:
        with db_factory() as db:
            admin = User(id="admin", username="admin", password_hash="hash")
            db.add(admin)
            db.commit()
            bootstrap_preview_data(db, admin)
            assert db.query(Task).count() == 0
            assert db.query(Report).count() == 0
            assert db.query(TaskEvent).count() == 0
            assert db.query(DispatchEvent).count() == 0

            db.add(Task(id="history", kind="benchmark", status="succeeded", created_by=admin.id))
            db.add(Report(id="history-report", task_id="history", kind="benchmark"))
            db.commit()
            bootstrap_preview_data(db, admin)
            assert [row.id for row in db.query(Task).all()] == ["history"]
            assert [row.id for row in db.query(Report).all()] == ["history-report"]
    finally:
        engine.dispose()
