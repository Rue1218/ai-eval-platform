"""个人记忆真实 ORM/HTTP 回归；SQLite 只验证功能，不声称覆盖 PostgreSQL 行锁。"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, BigInteger, Integer, MetaData, Text, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError, ErrorCode
from app.harness.context.meter import estimate_tokens
from app.harness.memory import personal
from app.main import app
from app.models import AuditLog, KnowledgeMemory, User, Workspace


@pytest.fixture
def memory_case():
    """仅在内存 SQLite 建四张复制表，不改共享 ORM、迁移或默认数据库。"""
    metadata = MetaData()
    for model in (User, Workspace, KnowledgeMemory, AuditLog):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif isinstance(column.type, BigInteger) and column.primary_key:
                column.type = Integer()
            elif column.name == "embedding":
                column.type = Text()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([User(id="owner", username="owner", password_hash="test"),
                    User(id="other", username="other", password_hash="test")])
        db.flush()
        db.add_all([Workspace(id="workspace", owner_id="owner", name="工作区"),
                    Workspace(id="foreign", owner_id="other", name="他人工作区"),
                    Workspace(id="deleted", owner_id="owner", name="已注销", deleted_at=datetime.now(UTC))])
    case = SimpleNamespace(factory=factory, user_id="owner")

    def current_user():
        """以可切换身份穿过真实路由，避免依赖登录 cookie 和外部服务。"""
        with factory() as db:
            return db.get(User, case.user_id)

    def database():
        """请求各自持有会话，异常和未提交事务在关闭时回滚。"""
        with factory() as db:
            yield db

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = database
    case.client = TestClient(app)
    try:
        yield case
    finally:
        case.client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)
        engine.dispose()


def _save(case, **overrides):
    """通过真实新增接口创建受校验记录。"""
    response = case.client.post("/api/agent/memories", json={"title": "回答习惯", "content": "请先给结论",
                                                            "category": "preference", **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def _seed(db, user_id="owner", **overrides):
    """构造历史行以验证数据库权限和脏存量边界。"""
    identity = str(uuid4())
    values = {"id": identity, "tenant_id": f"personal:{user_id}", "source_id": f"manual:{identity}",
              "source_version": 1, "content": "编译使用 gcc", "acl": "private", "acl_user_ids": [user_id],
              "meta": {"kind": "personal_memory", "schema_version": 1, "title": "编译器",
                       "category": "fact", "workspace_id": None}, "memory_revoked": False}
    values.update(overrides)
    row = KnowledgeMemory(**values)
    db.add(row)
    return row


def test_crud_versions_revocation_and_body_free_audit(memory_case):
    """CRUD 共用乐观版本，撤回清空存储正文，审计不存用户输入。"""
    saved = _save(memory_case, workspace_id="workspace")
    assert saved["source_id"] == f"manual:{saved['id']}"
    assert saved["workspace_name"] == "工作区" and saved["version"] == 1
    path = f"/api/agent/memories/{saved['id']}"
    update = {"title": "输出格式", "content": "结果使用表格", "category": "fact", "version": 1}
    changed = memory_case.client.put(path, json=update)
    assert changed.status_code == 200 and changed.json()["version"] == 2
    assert changed.json()["workspace_id"] is None
    assert memory_case.client.put(path, json=update).json()["code"] == "CONCURRENCY"
    assert memory_case.client.delete(path, params={"version": 1}).json()["code"] == "CONCURRENCY"
    deleted = memory_case.client.delete(path, params={"version": 2})
    assert deleted.status_code == 204 and not deleted.content
    assert memory_case.client.delete(path, params={"version": 3}).json()["code"] == "NOT_FOUND"
    assert memory_case.client.get("/api/agent/memories").json() == {"items": [], "total": 0}
    with memory_case.factory() as db:
        row = db.get(KnowledgeMemory, saved["id"])
        assert row.memory_revoked and row.content == "" and row.meta["title"] == "" and row.source_version == 3
        audits = list(db.scalars(select(AuditLog)))
        assert [audit.action for audit in audits] == ["agent_memory_create", "agent_memory_update", "agent_memory_revoke"]
        detail = json.dumps([audit.detail for audit in audits], ensure_ascii=False)
        assert not any(value in detail for value in ("输出格式", "结果使用表格", "请先给结论"))


def test_other_member_cannot_list_update_or_revoke(memory_case):
    """跨成员 ID 不代表授权，存在与否都只返回 NOT_FOUND。"""
    saved = _save(memory_case)
    memory_case.user_id = "other"
    assert memory_case.client.get("/api/agent/memories").json() == {"items": [], "total": 0}
    path = f"/api/agent/memories/{saved['id']}"
    assert memory_case.client.put(path, json={"title": "x", "content": "x", "version": 1}).json()["code"] == "NOT_FOUND"
    assert memory_case.client.delete(path, params={"version": 1}).json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize("workspace_id", ["foreign", "deleted", "missing"])
def test_binding_requires_own_active_workspace(memory_case, workspace_id):
    """保存不能绑定他人、注销或不存在的工作区。"""
    result = memory_case.client.post("/api/agent/memories", json={"title": "x", "content": "x", "workspace_id": workspace_id})
    assert result.status_code == 404 and result.json()["code"] == "NOT_FOUND"


def test_list_scope_search_pagination_and_deleted_workspace_management(memory_case):
    """列表精确区分全部/全局/工作区，搜索转义通配符，失效绑定仍能管理。"""
    global_row = _save(memory_case, title="通过率100%", category="fact")
    scoped = _save(memory_case, workspace_id="workspace", title="通过率1000", category="fact")
    assert memory_case.client.get("/api/agent/memories", params={"q": "%"}).json()["items"] == [global_row]
    assert memory_case.client.get("/api/agent/memories", params={"workspace_id": ""}).json()["items"] == [global_row]
    assert memory_case.client.get("/api/agent/memories", params={"workspace_id": "workspace"}).json()["items"] == [scoped]
    page = memory_case.client.get("/api/agent/memories", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    with memory_case.factory.begin() as db:
        db.get(Workspace, "workspace").deleted_at = datetime.now(UTC)
    page = memory_case.client.get("/api/agent/memories", params={"workspace_id": "workspace"}).json()
    assert page["items"][0]["workspace_name"] is None


@pytest.mark.parametrize("value", ["api_key=private-value", "password: private-value", "sk-secretvalue123",
                                  "Bearer abcdefgh12345", "-----BEGIN RSA PRIVATE KEY-----"])
def test_explicit_credentials_rejected_without_echo(memory_case, value):
    """已知凭据写法拒绝保存，统一错误不回显秘密。"""
    response = memory_case.client.post("/api/agent/memories", json={"title": "配置", "content": value})
    assert response.status_code == 400 and response.json()["code"] == "VALIDATION"
    assert value not in response.text


def test_plain_security_words_remain_valid_and_dirty_history_is_filtered(memory_case):
    """正常 token/password 说明可以保存，旧宽 ACL、错误 schema 与秘密正文不可返回或召回。"""
    saved = _save(memory_case, content="token 预算为2048，password 字段不要放入日志")
    with memory_case.factory.begin() as db:
        _seed(db, acl="tenant")
        _seed(db, acl_user_ids=["owner", "other"])
        _seed(db, tenant_id="personal:other")
        _seed(db, source_id="conversation:fake")
        _seed(db, meta={"kind": "old", "schema_version": 1})
        _seed(db, meta={"kind": "personal_memory", "schema_version": "invalid"})
        _seed(db, meta={"kind": "personal_memory", "schema_version": "1", "title": "old", "category": "preference"})
        _seed(db, content="sk-dirtysecret1234")
    result = memory_case.client.get("/api/agent/memories").json()
    assert result == {"items": [saved], "total": 1}
    with memory_case.factory() as db:
        assert personal.recall_personal_memories(db, "owner", None, "编译") == [saved]


@pytest.mark.parametrize("field,value", [("user_id", "other"), ("acl", "tenant"), ("embedding", []),
                                         ("source_id", "conversation:fake"), ("title", " "),
                                         ("content", "x" * 2001)])
def test_request_contract_rejects_extra_or_invalid_fields_without_echo(memory_case, field, value):
    """请求禁止身份伪造和超限正文，校验失败不会在错误体中回显内容。"""
    response = memory_case.client.post("/api/agent/memories", json={"title": "memo", "content": "private-marker", field: value})
    assert response.status_code == 400 and response.json()["code"] == "VALIDATION"
    assert "private-marker" not in response.text


@pytest.mark.parametrize("version", [True, "1", 0, -1, 1.5])
def test_update_requires_strict_positive_integer_version(memory_case, version):
    """布尔、字符串和非正整数不能冒充编辑版本。"""
    response = memory_case.client.put("/api/agent/memories/unused", json={"title": "x", "content": "x", "version": version})
    assert response.status_code == 400 and response.json()["code"] == "VALIDATION"


def test_quota_counts_active_memories_and_revoke_frees_capacity(memory_case):
    """200 条上限检查和保存共事务，撤回后可新增。"""
    with memory_case.factory.begin() as db:
        rows = [_seed(db) for _ in range(personal.MAX_MEMORIES)]
    response = memory_case.client.post("/api/agent/memories", json={"title": "new", "content": "new"})
    assert response.status_code == 400 and response.json()["code"] == "VALIDATION"
    assert memory_case.client.delete(f"/api/agent/memories/{rows[0].id}", params={"version": 1}).status_code == 204
    _save(memory_case)


def test_recall_relevance_scope_budget_and_fresh_revisions(memory_case):
    """召回只含相关事实与常用偏好，按作用域与整体预算选择完整记录，并即时反映修改。"""
    preference_row = _save(memory_case)
    fact = _save(memory_case, title="编译流程", content="编译使用 gcc", category="fact", workspace_id="workspace")
    _save(memory_case, title="旅行", content="巴黎的行程", category="fact")
    with memory_case.factory() as db:
        assert personal.recall_personal_memories(db, "owner", None, "编译") == [preference_row]
        assert [item["id"] for item in personal.recall_personal_memories(db, "owner", "workspace", "编译")] == [fact["id"], preference_row["id"]]
        assert personal.recall_personal_memories(db, "owner", "foreign", "编译") == [preference_row]
        assert personal.recall_personal_memories(db, "owner", None, "无关问题") == [preference_row]
        memory_case.client.put(f"/api/agent/memories/{preference_row['id']}", json={"title": "更新", "content": "请用中文", "category": "preference", "version": 1})
        refreshed = personal.recall_personal_memories(db, "owner", None, "")
        assert refreshed[0]["version"] == 2 and refreshed[0]["content"] == "请用中文"
    for index in range(7):
        _save(memory_case, title=f"格式{index}", content="中" * 1900)
    with memory_case.factory() as db:
        selected = personal.recall_personal_memories(db, "owner", None, "")
        assert 1 <= len(selected) <= 5
        assert estimate_tokens(json.dumps(selected, ensure_ascii=False, sort_keys=True)) <= personal.RECALL_TOKEN_BUDGET
        assert all(item["content"] in {"中" * 1900, "请用中文"} for item in selected)


def test_recall_has_no_unrelated_fact_fallback_and_revoked_workspace_is_excluded(memory_case):
    """没有相关事实就返回空列表，工作区注销后下一次请求不能继续召回其记忆。"""
    _save(memory_case, title="编译", content="使用 gcc", category="fact", workspace_id="workspace")
    with memory_case.factory() as db:
        assert personal.recall_personal_memories(db, "owner", "workspace", "unrelated") == []
        assert len(personal.recall_personal_memories(db, "owner", "workspace", "编译")) == 1
        with memory_case.factory.begin() as other:
            other.get(Workspace, "workspace").deleted_at = datetime.now(UTC)
        assert personal.recall_personal_memories(db, "owner", "workspace", "编译") == []


def test_database_failure_does_not_log_memory_sql_parameters(memory_case, monkeypatch, caplog):
    """SQL 异常转换为固定业务错误，避免全局堆栈记录绑定的正文。"""
    def fail(*args, **kwargs):
        """模拟数据库异常携带敏感 SQL 参数的常见情况。"""
        raise IntegrityError("insert", {"content": "private-marker"}, RuntimeError("private-marker"))

    monkeypatch.setattr(personal, "create_personal_memory", fail)
    response = memory_case.client.post("/api/agent/memories", json={"title": "x", "content": "private-marker"})
    assert response.status_code == 500 and response.json()["code"] == "INTERNAL"
    assert "private-marker" not in response.text and "private-marker" not in caplog.text


def test_disabled_member_cannot_recall_or_write(memory_case):
    """运行期再次检查成员状态，不复用先前已授权的召回。"""
    _save(memory_case)
    with memory_case.factory.begin() as db:
        db.get(User, "owner").disabled = True
    with memory_case.factory() as db:
        assert personal.recall_personal_memories(db, "owner", None, "") == []
        with pytest.raises(AppError) as exc:
            personal.create_personal_memory(db, "owner", title="x", content="x")
        assert exc.value.code == ErrorCode.UNAUTHORIZED
