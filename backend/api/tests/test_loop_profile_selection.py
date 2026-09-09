"""按回合协议档选择与 Agent UI 脱敏能力投影。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agent import loop_wiring
from app.errors import AppError, ErrorCode
from app.models import ProtocolProfile, Setting
from app.routers import profiles as profiles_router
from app.routers import sessions


class _Query:
    """最小查询替身，仅覆盖协议档能力投影的排序和列举。"""

    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_args):
        """测试行已按预期顺序提供，无需模拟 SQL 排序。"""
        return self

    def all(self):
        """返回独立列表，避免投影过程修改测试行。"""
        return list(self.rows)


class _Db:
    """按模型和主键读取受控协议档，不提供任何真实数据库或环境凭据。"""

    def __init__(self, rows, settings):
        self.rows = rows
        self.by_id = {row.id: row for row in rows}
        self.settings = settings

    def get(self, model, key):
        """模拟授权解析需要的主键读取。"""
        if model is ProtocolProfile:
            return self.by_id.get(key)
        if model is Setting:
            value = self.settings.get(key)
            return SimpleNamespace(value=value) if value is not None else None
        raise AssertionError(f"未预期的模型读取：{model}")

    def query(self, model):
        """Agent UI 只允许列举协议档。"""
        assert model is ProtocolProfile
        return _Query(self.rows)


def _profile(profile_id: str, *, usages=None):
    """构造具备完整模型边界字段的无密钥协议档测试行。"""
    return SimpleNamespace(
        id=profile_id,
        name=f"Profile {profile_id}",
        protocol="openai_chat",
        base_url=f"https://{profile_id}.invalid/v1",
        model="deepseek-chat",
        usages=["agent"] if usages is None else usages,
        anthropic_version=None,
        context_window=64000,
        max_output_tokens=4096,
        updated_at=datetime(2026, 9, 9, tzinfo=UTC),
    )


@pytest.fixture
def profile_db(monkeypatch):
    """让授权逻辑只读取替身连接，记录全局别名是否被不当复用。"""
    rows = [_profile("default"), _profile("alternate"), _profile("not-agent", usages=["benchmark"])]
    db = _Db(rows, {
        "agent_profile_id": "default",
        "agent_reasoning": {"enabled": True, "effort": "high"},
    })
    connections = []

    def connection(profile, *, allow_global_alias=False):
        """模拟本地受控环境读取，不把凭据返回到 API 投影。"""
        connections.append((profile.id, allow_global_alias))
        return profile.base_url, profile.model, "test-only-key"

    monkeypatch.setattr(profiles_router, "_profile_connection", connection)
    return SimpleNamespace(db=db, connections=connections)


def test_authorized_profile_selects_requested_agent_profile_and_revalidates_effort(profile_db):
    """显式 profile_id 使用自身连接配置，并在 SDK 分配前验证 DeepSeek 档位。"""
    snapshot, context_window = loop_wiring.authorized_profile(
        profile_db.db,
        {"profile_id": "alternate", "reasoning_effort": "max"},
    )
    assert snapshot.profile_id == "alternate"
    assert snapshot.config.reasoning_effort == "max"
    assert context_window == 64000
    assert profile_db.connections == [("alternate", False)]

    with pytest.raises(AppError) as caught:
        loop_wiring.authorized_profile(profile_db.db, {"profile_id": "not-agent"})
    assert caught.value.code == ErrorCode.VALIDATION

    with pytest.raises(AppError) as caught:
        loop_wiring.authorized_profile(
            profile_db.db,
            {"profile_id": "alternate", "reasoning_effort": "xhigh"},
        )
    assert caught.value.code == ErrorCode.VALIDATION


def test_agent_ui_lists_only_safe_selectable_profile_metadata(profile_db):
    """协议档能力以 resolver 计算；响应不含连接地址或模型凭据。"""
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    user = SimpleNamespace(id="member", role="member")

    payload = sessions._loop_ui(profile_db.db, user, request)

    fields = {
        "id", "name", "version", "model", "protocol", "allowed_efforts", "default_effort",
    }
    assert [item["id"] for item in payload["profiles"]] == ["default", "alternate"]
    assert all(set(item) == fields for item in payload["profiles"])
    assert payload["profile"] is not None
    assert set(payload["profile"]) == fields
    assert payload["profile"]["id"] == "default"
    assert payload["profile"]["allowed_efforts"] == ["off", "low", "medium", "high", "max"]
    assert payload["profile"]["default_effort"] == "high"
    assert payload["enabled"] is True
    rendered = str(payload)
    assert "test-only-key" not in rendered
    assert "https://default.invalid" not in rendered
    assert "https://alternate.invalid" not in rendered


@pytest.mark.parametrize("protocol,model", [
    ("anthropic_messages", "unknown-compatible-model"),
    ("openai_chat", "stepfun-ai/step-3.7-flash"),
])
def test_compatible_default_profile_survives_global_reasoning_preference(profile_db, protocol, model):
    """兼容协议档不因全局思考偏好消失；能力与实际请求使用相同回退结果。"""
    row = profile_db.db.by_id["default"]
    row.protocol, row.model = protocol, model
    snapshot, _ = loop_wiring.authorized_profile(profile_db.db, {})
    assert snapshot.config.reasoning_enabled is False
    payload = sessions._loop_ui(
        profile_db.db, SimpleNamespace(id="member", role="member"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )
    assert payload["profile"]["id"] == "default"
    assert payload["default_effort"] == "off"
    assert payload["unavailable_reason"] is None
    with pytest.raises(AppError) as caught:
        loop_wiring.authorized_profile(profile_db.db, {"reasoning_effort": "high"})
    assert caught.value.code == ErrorCode.VALIDATION


@pytest.mark.parametrize("model,allowed", [
    ("deepseek-v4-flash-0731", ["off", "high", "max"]),
    ("deepseek-v4-pro-0813", ["off", "high", "max"]),
    ("qwen3.6-flash", ["off", "low", "medium", "high", "xhigh", "max"]),
    ("qwen3.6-flash-2026-04-16", ["off", "low", "medium", "high", "xhigh", "max"]),
])
def test_server_model_capabilities_match_each_authorized_request(profile_db, model, allowed):
    """服务器型号可展示的每个档位，都必须能通过回合授权和模型参数解析。"""
    from app.llm.resolver import resolve_request

    row = profile_db.db.by_id["default"]
    row.protocol, row.model = "anthropic_messages", model
    payload = sessions._loop_ui(
        profile_db.db, SimpleNamespace(id="member", role="member"),
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )
    assert payload["profile"]["allowed_efforts"] == allowed
    assert payload["default_effort"] == "high"
    for effort in allowed:
        snapshot, _ = loop_wiring.authorized_profile(profile_db.db, {"reasoning_effort": effort})
        request = resolve_request(snapshot, messages=[])
        assert request.reasoning_effort == effort
        assert request.provider_options["thinking"]["type"] == (
            "disabled" if effort == "off" else "enabled"
        )
