"""协议档连接探活的超时契约测试。"""

from types import SimpleNamespace

from app.adapters import DEFAULT_TIMEOUT_S
from app.routers import profiles


class _ProfileQuery:
    """提供探活路由所需的最小查询链，避免测试依赖真实数据库。"""

    def __init__(self, profile: object):
        self.profile = profile

    def filter(self, *_args: object) -> "_ProfileQuery":
        """保持 SQLAlchemy 的链式筛选外形。"""
        return self

    def first(self) -> object:
        """返回预置协议档。"""
        return self.profile


class _ProfileDb:
    """提供探活路由所需的最小数据库对象。"""

    def __init__(self, profile: object):
        self.profile = profile

    def query(self, *_args: object) -> _ProfileQuery:
        """返回可继续筛选的单条协议档查询。"""
        return _ProfileQuery(self.profile)


def test_profile_check_uses_shared_protocol_timeout(monkeypatch):
    """冷启动模型的页面探活必须沿用协议调用的 30 秒默认超时。"""
    profile = SimpleNamespace(id="profile-id", protocol="openai_chat", anthropic_version=None)
    captured: dict[str, object] = {}

    def fake_connection(*_args: object, **_kwargs: object) -> tuple[str, str, str]:
        """返回脱敏的固定测试连接配置。"""
        return ("https://example.test/v1", "example-model", "test-key")

    def fake_check(config) -> dict:
        """记录超时参数，并模拟成功的最小上游响应。"""
        captured.update(timeout_s=config.timeout_s, max_tokens=config.max_tokens, reasoning_enabled=config.reasoning_enabled)
        return {"ok": True, "latency_ms": 12, "model": "example-model"}

    monkeypatch.setattr(profiles, "_profile_connection", fake_connection)
    monkeypatch.setattr(profiles, "check_model_connection", fake_check)

    response = profiles.check_profile("profile-id", _ProfileDb(profile), SimpleNamespace())

    assert response == {"ok": True, "latency_ms": 12, "model": "example-model"}
    assert captured["timeout_s"] == DEFAULT_TIMEOUT_S == 30.0

    assert captured["max_tokens"] == 8192
