"""安全加固回归：RAG 探活不泄露平台密钥/不做内网探测；重置他人密码需二次确认。

对应审查结论 P0-1（`/api/admin/rag-models/check` 把平台密钥发往请求方指定的
任意地址）与 P0-2（任意成员可重置他人密码并踢下线）。
"""

import socket
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import JSON, BigInteger, Integer, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.errors import AppError, ErrorCode
from app.models import AuditLog, User
from app.routers import admin as admin_routes
from app.routers import users as user_routes
from app.schemas import ResetPasswordRequest
from app.security import hash_password

# ─── RAG 模型探活 ────────────────────────────────────────────────


class _Captured:
    """记录探活请求实际发出的地址、头与载荷。"""

    def __init__(self) -> None:
        self.url = ""
        self.headers: dict[str, str] = {}
        self.json: dict | None = None


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """替换 httpx.Client：不产生真实网络请求。"""

    captured = _Captured()
    response = _FakeResponse(200, "ok")

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        _FakeClient.captured.url = url
        _FakeClient.captured.headers = dict(headers or {})
        _FakeClient.captured.json = json
        return _FakeClient.response


@pytest.fixture
def rag_env(monkeypatch: pytest.MonkeyPatch):
    """已保存的全局 RAG 配置（含平台密钥）+ 假 httpx 客户端。"""
    values = SimpleNamespace(
        embedding_base_url="https://saved.example.com/v1",
        embedding_model="text-embedding-3-small",
        embedding_api_key="platform-embedding-secret",
        reranker_base_url="https://saved.example.com/v1",
        reranker_model="bge-reranker-v2",
        reranker_api_key="platform-reranker-secret",
    )
    monkeypatch.setattr(admin_routes, "read_global_rag_env", lambda: values)
    _FakeClient.captured = _Captured()
    _FakeClient.response = _FakeResponse(200, "ok")
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    # SSRF 校验会对域名做真实解析，测试环境无 DNS：固定解析到公网地址。
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
        ],
    )
    return values


_ACTOR = SimpleNamespace(id="member-1")


def test_rag_check_never_sends_platform_key_to_arbitrary_target(rag_env):
    """临时目标未显式给 key 时不得携带平台密钥。"""
    body = admin_routes.RagCheckIn(
        target="embedding",
        base_url="https://attacker.example.net/v1",
        model="text-embedding-3-small",
    )

    result = admin_routes.check_rag_model(body, user=_ACTOR)

    assert result["ok"] is True
    assert "Authorization" not in _FakeClient.captured.headers
    assert _FakeClient.captured.url == "https://attacker.example.net/v1/embeddings"


def test_rag_check_reuses_platform_key_only_for_saved_target(rag_env):
    """与已保存配置同源的目标才复用平台密钥，保证保存后探活体验不变。"""
    body = admin_routes.RagCheckIn(
        target="embedding",
        base_url="https://saved.example.com/v1",
        model="text-embedding-3-small",
    )

    admin_routes.check_rag_model(body, user=_ACTOR)

    assert _FakeClient.captured.headers["Authorization"] == "Bearer platform-embedding-secret"


def test_rag_check_explicit_key_is_used(rag_env):
    """请求方显式提供的 key 优先，且不会替换成平台密钥。"""
    body = admin_routes.RagCheckIn(
        target="reranker",
        base_url="https://third-party.example.net/v1",
        model="bge-reranker-v2",
        api_key="user-supplied-key",
    )

    admin_routes.check_rag_model(body, user=_ACTOR)

    assert _FakeClient.captured.headers["Authorization"] == "Bearer user-supplied-key"


def test_rag_check_rejects_internal_target(rag_env):
    """临时指定的内网/回环地址一律拒绝（SSRF）。"""
    body = admin_routes.RagCheckIn(
        target="embedding",
        base_url="http://127.0.0.1:8080/v1",
        model="m",
    )

    with pytest.raises(AppError) as excinfo:
        admin_routes.check_rag_model(body, user=_ACTOR)

    assert excinfo.value.code == ErrorCode.VALIDATION
    assert _FakeClient.captured.url == ""


def test_rag_check_trusts_saved_internal_target(rag_env):
    """已保存配置允许是内网地址（如自建 Embedding 服务），不被 SSRF 误杀。"""
    rag_env.embedding_base_url = "http://127.0.0.1:11434/v1"
    body = admin_routes.RagCheckIn(
        target="embedding",
        base_url="http://127.0.0.1:11434/v1",
        model="nomic-embed-text",
    )

    assert admin_routes.check_rag_model(body, user=_ACTOR)["ok"] is True


def test_rag_check_does_not_echo_upstream_body(rag_env):
    """上游失败只回状态码，正文（可能含内部信息）不得透传。"""
    _FakeClient.response = _FakeResponse(500, "internal-secret-should-not-leak")
    body = admin_routes.RagCheckIn(
        target="embedding",
        base_url="https://saved.example.com/v1",
        model="text-embedding-3-small",
    )

    result = admin_routes.check_rag_model(body, user=_ACTOR)

    assert result["ok"] is False
    assert result["code"] == 500
    assert "internal-secret-should-not-leak" not in result["message"]


def test_rag_check_rejects_non_http_scheme(rag_env):
    """只有 http(s) 是合法探活目标。"""
    body = admin_routes.RagCheckIn(
        target="embedding",
        base_url="file:///etc/passwd",
        model="m",
    )

    with pytest.raises(AppError) as excinfo:
        admin_routes.check_rag_model(body, user=_ACTOR)

    assert excinfo.value.code == ErrorCode.VALIDATION


# ─── 重置密码二次确认 ────────────────────────────────────────────


@pytest.fixture
def users_db():
    """仅承载 User 与 AuditLog 的内存库（JSONB/BigInteger 适配 sqlite）。"""
    metadata = MetaData()
    pending = [User.__table__, AuditLog.__table__]
    while pending:
        table = pending.pop()
        if table.name in metadata.tables:
            continue
        copied = table.to_metadata(metadata)
        for column in copied.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif column.primary_key and isinstance(column.type, BigInteger):
                column.type = Integer()
        pending.extend(foreign.column.table for foreign in table.foreign_keys)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    metadata.create_all(engine)
    try:
        with sessionmaker(engine, autoflush=False)() as db:
            db.add_all(
                [
                    User(
                        id="self",
                        username="self",
                        password_hash=hash_password("self-pass1"),
                    ),
                    User(
                        id="other",
                        username="other",
                        password_hash=hash_password("other-pass1"),
                    ),
                ]
            )
            db.commit()
            yield db
    finally:
        engine.dispose()


def _request() -> SimpleNamespace:
    return SimpleNamespace(client=None)


def _me(db) -> User:
    return db.query(User).filter(User.id == "self").one()


def test_reset_other_password_requires_current_password(users_db):
    """重置他人密码缺少二次确认时拒绝，且目标未被改动。"""
    with pytest.raises(AppError) as excinfo:
        user_routes.reset_password(
            "other",
            ResetPasswordRequest(password="newpass123"),
            _request(),
            db=users_db,
            user=_me(users_db),
        )

    assert excinfo.value.code == ErrorCode.VALIDATION
    users_db.expire_all()
    assert users_db.query(User).filter(User.id == "other").one().auth_version == 1
    assert users_db.query(AuditLog).count() == 0


def test_reset_other_password_rejects_wrong_current_password(users_db):
    """二次确认密码错误时拒绝。"""
    with pytest.raises(AppError) as excinfo:
        user_routes.reset_password(
            "other",
            ResetPasswordRequest(password="newpass123", current_password="wrong-pass1"),
            _request(),
            db=users_db,
            user=_me(users_db),
        )

    assert excinfo.value.code == ErrorCode.VALIDATION
    users_db.expire_all()
    assert users_db.query(User).filter(User.id == "other").one().auth_version == 1


def test_reset_other_password_succeeds_with_current_password(users_db):
    """二次确认通过后重置成功：目标 auth_version 递增并留审计。"""
    me = _me(users_db)

    user_routes.reset_password(
        "other",
        ResetPasswordRequest(password="newpass123", current_password="self-pass1"),
        _request(),
        db=users_db,
        user=me,
    )

    users_db.expire_all()
    target = users_db.query(User).filter(User.id == "other").one()
    assert target.auth_version == 2
    audit = users_db.query(AuditLog).filter(AuditLog.action == "password_reset").one()
    assert audit.detail == {"self": False}
    assert audit.target_id == "other"


def test_reset_own_password_needs_no_current_password(users_db):
    """本人重置自己的密码不需要二次确认。"""
    me = _me(users_db)

    user_routes.reset_password(
        "self",
        ResetPasswordRequest(password="newpass123"),
        _request(),
        db=users_db,
        user=me,
    )

    users_db.expire_all()
    assert users_db.query(User).filter(User.id == "self").one().auth_version == 2
    audit = users_db.query(AuditLog).filter(AuditLog.action == "password_reset").one()
    assert audit.detail == {"self": True}
