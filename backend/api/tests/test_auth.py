"""Cookie 鉴权路由契约与密码策略单测（不依赖数据库连接）。

未登录请求在依赖注入阶段即被 401 拒绝，不会触达数据库查询；
登录失败路径用最小 DB 替身验证审计写入；密码策略为纯函数单测。
"""

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.errors import AppError, ErrorCode
from app.main import app
from app.routers.auth import COOKIE_NAME, _validate_password
from app.security import hash_password


class _FakeDb:
    """最小 DB 替身：支撑登录失败路径的查询、审计写入与提交。"""

    def __init__(self, user=None) -> None:
        self.user = user
        self.added: list = []

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.user

    def add(self, row) -> None:
        self.added.append(row)

    def commit(self) -> None:
        pass

    def refresh(self, row) -> None:
        pass


def _fake_user(**overrides):
    """构造登录判定所需字段的账号替身（不落库）。"""
    from types import SimpleNamespace

    values = {
        "id": "u-1",
        "username": "alice",
        "password_hash": hash_password("abcd1234"),
        "auth_version": 1,
        "disabled": False,
        "last_login_at": None,
        "last_login_ip": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _login_with(user) -> tuple:
    """用替身 DB 发起登录，返回（响应, 替身 DB）。"""
    fake = _FakeDb(user)
    app.dependency_overrides[get_db] = lambda: fake
    try:
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "abcd1234"})
    finally:
        app.dependency_overrides.clear()
    return resp, fake


class TestPasswordPolicy:
    """密码策略：至少 8 位且同时包含字母与数字。"""

    def test_accepts_letter_digit_combo(self) -> None:
        """合法密码不抛异常。"""
        _validate_password("abcd1234")
        _validate_password("A1" + "x" * 6)

    @pytest.mark.parametrize("bad", ["a1b2c3", "", "abcdefgh", "12345678"])
    def test_rejects_invalid_password(self, bad: str) -> None:
        """过短 / 纯字母 / 纯数字一律 VALIDATION。"""
        with pytest.raises(AppError) as error:
            _validate_password(bad)
        assert error.value.code == ErrorCode.VALIDATION


class TestLoginFailurePaths:
    """登录失败：一律 401 UNAUTHORIZED 并落 login_failed 审计。"""

    def test_unknown_user_rejected(self) -> None:
        resp, fake = _login_with(None)
        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"
        assert fake.added and fake.added[0].action == "login_failed"

    def test_disabled_user_rejected(self) -> None:
        resp, fake = _login_with(_fake_user(disabled=True))
        assert resp.status_code == 401
        assert fake.added and fake.added[0].action == "login_failed"

    def test_wrong_password_rejected(self) -> None:
        resp, fake = _login_with(_fake_user(password_hash=hash_password("other-999")))
        assert resp.status_code == 401
        assert fake.added and fake.added[0].action == "login_failed"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/auth/me", None),
        ("POST", "/api/auth/change-password", {"old_password": "abcd1234", "new_password": "abcd5678"}),
        ("POST", "/api/auth/ws-ticket", None),
    ],
)
def test_auth_endpoints_require_login(method: str, path: str, body) -> None:
    """受保护接口未登录一律 401 UNAUTHORIZED。"""
    client = TestClient(app)
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_logout_clears_cookie() -> None:
    """注销清空 Cookie（无需登录，幂等返回 ok）。"""
    client = TestClient(app)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert COOKIE_NAME in resp.headers.get("set-cookie", "")
