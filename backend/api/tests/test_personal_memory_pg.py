"""个人记忆的真实 PostgreSQL 权限、并发和事务回归；只连接显式隔离测试库。"""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.errors import AppError, ErrorCode
from app.harness.memory import personal
from app.models import AuditLog, KnowledgeMemory
from tests import test_loop_store_pg as store_fixtures

pg_case = store_fixtures.pg_case


@pytest.fixture
def memory_pg(pg_case):
    """只清理本例 UUID 命名空间和无正文审计，再交原夹具清理用户。"""
    try:
        yield pg_case
    finally:
        with pg_case.factory.begin() as db:
            db.execute(delete(KnowledgeMemory).where(KnowledgeMemory.tenant_id == f"personal:{pg_case.user_id}"))
            db.execute(delete(AuditLog).where(AuditLog.user_id == pg_case.user_id))


def _row(user_id: str, **overrides):
    """创建独立手动来源行，供脏历史与配额边界测试。"""
    identity = str(uuid4())
    values = {"id": identity, "tenant_id": f"personal:{user_id}", "source_id": f"manual:{identity}",
              "source_version": 1, "content": "输出使用中文", "acl": "private", "acl_user_ids": [user_id],
              "meta": {"kind": "personal_memory", "schema_version": 1, "title": "回复偏好",
                       "category": "preference", "workspace_id": None}, "memory_revoked": False}
    values.update(overrides)
    return KnowledgeMemory(**values)


def test_pg_json_acl_and_corrupt_schema_do_not_leak_or_break_reads(memory_pg):
    """真实 JSONB 精确隔离旧宽 ACL，非法版本文本不会触发整数转换错误。"""
    with memory_pg.factory.begin() as db:
        valid = _row(memory_pg.user_id)
        db.add_all([valid, _row(memory_pg.user_id, acl="tenant"),
                    _row(memory_pg.user_id, acl_user_ids=[memory_pg.user_id, memory_pg.observer_id]),
                    _row(memory_pg.user_id, content="sk-oldsecret12345"),
                    _row(memory_pg.user_id, meta={"kind": "personal_memory", "schema_version": "broken"}),
                    _row(memory_pg.user_id, meta={"kind": "personal_memory", "schema_version": "1",
                                                 "title": "旧格式", "category": "preference"})])
    with memory_pg.factory() as db:
        assert [row["id"] for row in personal.list_personal_memories(db, memory_pg.user_id)["items"]] == [valid.id]
        assert [row["id"] for row in personal.recall_personal_memories(db, memory_pg.user_id, None, "")] == [valid.id]
        assert personal.list_personal_memories(db, memory_pg.observer_id)["total"] == 0


def test_pg_quota_user_lock_prevents_parallel_201st_memory(memory_pg):
    """第 200/201 条并发保存按用户锁串行，后者读到已提交配额并安全拒绝。"""
    with memory_pg.factory.begin() as db:
        db.add_all([_row(memory_pg.user_id) for _ in range(personal.MAX_MEMORIES - 1)])
    ready = Queue()

    def second_create():
        """报告真实数据库连接身份，以阻塞关系代替固定时间猜测。"""
        try:
            with memory_pg.factory.begin() as db:
                ready.put(db.scalar(text("SELECT pg_backend_pid()")))
                personal.create_personal_memory(db, memory_pg.user_id, title="第201条", content="不得超额")
        except AppError as exc:
            return exc.code
        return None

    with memory_pg.factory() as first, ThreadPoolExecutor(max_workers=1) as executor:
        first_pid = first.scalar(text("SELECT pg_backend_pid()"))
        personal.create_personal_memory(first, memory_pg.user_id, title="第200条", content="允许保存")
        future = executor.submit(second_create)
        try:
            second_pid = ready.get(timeout=5)
            deadline = monotonic() + 5
            with memory_pg.factory() as observer:
                while first_pid not in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid}):
                    assert monotonic() < deadline, "第二次保存没有等待用户锁"
                    Event().wait(0.01)
            first.commit()
            assert future.result(timeout=5) == ErrorCode.VALIDATION
        finally:
            first.rollback()
    with memory_pg.factory() as db:
        assert personal.list_personal_memories(db, memory_pg.user_id)["total"] == personal.MAX_MEMORIES


def test_pg_optimistic_version_and_withdrawal_take_effect_immediately(memory_pg):
    """不同事务只接受最新版本，撤回后读取和召回立即消失且正文清空。"""
    with memory_pg.factory.begin() as db:
        original = personal.create_personal_memory(db, memory_pg.user_id, title="语言", content="使用中文", category="preference")
    with memory_pg.factory.begin() as db:
        changed = personal.update_personal_memory(db, memory_pg.user_id, original["id"], version=1,
                                                  title="语言", content="使用英文", category="preference")
        assert changed["version"] == 2
    with memory_pg.factory.begin() as db:
        with pytest.raises(AppError) as exc:
            personal.revoke_personal_memory(db, memory_pg.user_id, original["id"], 1)
        assert exc.value.code == ErrorCode.CONCURRENCY
    with memory_pg.factory.begin() as db:
        personal.revoke_personal_memory(db, memory_pg.user_id, original["id"], 2)
    with memory_pg.factory() as db:
        assert personal.recall_personal_memories(db, memory_pg.user_id, None, "") == []
        row = db.get(KnowledgeMemory, original["id"])
        assert row.content == "" and row.meta["title"] == "" and row.source_version == 3


def test_pg_memory_and_audit_rollback_together(memory_pg):
    """保存后的事务故障同时回滚正文和审计，不能留下半条记忆。"""
    with pytest.raises(RuntimeError, match="模拟事务失败"):
        with memory_pg.factory.begin() as db:
            personal.create_personal_memory(db, memory_pg.user_id, title="回滚", content="不应保留")
            db.flush()
            raise RuntimeError("模拟事务失败")
    with memory_pg.factory() as db:
        assert personal.list_personal_memories(db, memory_pg.user_id)["total"] == 0
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.user_id == memory_pg.user_id)) == 0
