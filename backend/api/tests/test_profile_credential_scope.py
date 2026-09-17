"""凭据只在同源服务中隐式复用，所有密钥和网络端点均为测试替身。"""

from types import SimpleNamespace

import pytest
from shared.model_urls import same_origin

from app import profile_env
from app.errors import AppError, ErrorCode
from app.routers import profiles
from app.schemas import FetchModelsIn, ProfileProbeUpdate, ProfileUpdate
from tests.test_profile_check import _ProfileDb


@pytest.mark.parametrize("target,allowed", [
    ("https://HOST.invalid:443/v1", True), ("https://host.invalid/other", True),
    ("http://host.invalid", False), ("https://host.invalid:8443", False), ("https://host.invalid:0", False),
    ("https://host.invalid.attacker.invalid", False), ("https://host.invalid@other.invalid", False),
    ("https://host.invalid:bad", False), ("https://host.invalid\\@other.invalid", False),
])
def test_credentials_require_same_origin(target, allowed):
    """路径调整允许保留凭据，降级协议、端口、伪装域名和畸形 URL 均拒绝。"""
    assert same_origin("https://host.invalid", target) is allowed


@pytest.mark.parametrize("route", ["probe", "models", "update"])
def test_profile_edits_reject_cross_origin_before_network(monkeypatch, route):
    """三类接口在任何上游请求或保存前拒绝将隐藏凭据转发到新源。"""
    profile = SimpleNamespace(id="unit-profile", protocol="openai_responses", anthropic_version=None)
    monkeypatch.setattr(profiles, "_profile_connection", lambda *a, **k: ("https://original.invalid", "unit", "fake-key"))
    monkeypatch.setattr(profiles, "read_profile_env", lambda *a: SimpleNamespace(full_url=False))
    db = _ProfileDb(profile)
    with pytest.raises(AppError) as caught:
        if route == "probe":
            body = ProfileProbeUpdate(name="unit", protocol="openai_responses", base_url="https://different.invalid",
                                      model="unit", reasoning_template_id="newapi-no-reasoning-v1")
            profiles.probe_update_profile(profile.id, body, SimpleNamespace(), db, SimpleNamespace())
        elif route == "models":
            profiles.fetch_models(FetchModelsIn(profile_id=profile.id, base_url="https://different.invalid"), db, SimpleNamespace())
        else:
            profiles._update_profile(profile.id, ProfileUpdate(base_url="https://different.invalid"), SimpleNamespace(), db, SimpleNamespace())
    assert caught.value.code == ErrorCode.VALIDATION
    assert "重新填写" in caught.value.message
    assert "fake-key" not in caught.value.message


def test_explicit_replacement_key_is_used_for_new_origin(monkeypatch):
    """明确填写的新密钥可以用于新主机，旧密钥不能参与实际请求。"""
    seen = []
    profile = SimpleNamespace(id="unit", protocol="openai_responses", anthropic_version=None)
    monkeypatch.setattr(profiles, "_profile_connection", lambda *a, **k: ("https://old.invalid", "unit", "fake-old"))
    monkeypatch.setattr(profiles, "read_profile_env", lambda *a: SimpleNamespace(full_url=False))
    monkeypatch.setattr(profiles, "fetch_remote_models", lambda **kw: seen.append(kw) or [])
    profiles.fetch_models(FetchModelsIn(profile_id="unit", base_url="https://new.invalid", api_key="fake-new"),
                          _ProfileDb(profile), SimpleNamespace())
    assert seen[0]["api_key"] == "fake-new"


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
def test_auxiliary_endpoint_edit_cannot_reuse_hidden_key(monkeypatch, kind):
    """独立 Embedding/Reranker 地址的修改也不能复用原服务凭据。"""
    from shared.profile_env import ProfileEnvValues

    profile = SimpleNamespace(id="unit", protocol="openai_chat", anthropic_version=None)
    env = ProfileEnvValues(base_url=None, model=None, api_key=None,
                           **{f"{kind}_base_url": "https://old.invalid", f"{kind}_api_key": "fake-hidden"})
    monkeypatch.setattr(profiles, "read_profile_env", lambda *a: env)
    monkeypatch.setattr(profiles, "_profile_connection", lambda *a, **k: ("https://main.invalid", "unit", "fake-main"))
    body = ProfileUpdate(**{f"{kind}_base_url": "https://new.invalid"})
    with pytest.raises(AppError, match="重新填写"):
        profiles._update_profile("unit", body, SimpleNamespace(), _ProfileDb(profile), SimpleNamespace())


@pytest.mark.parametrize("target,expected", [
    ("https://unrelated.invalid", None), ("https://openai.attacker.invalid", None),
    ("https://unrelated.invalid/openai", None), ("https://api.openai.com", "fake-global"),
    ("https://gateway.invalid/v1", "fake-profile"), ("http://gateway.invalid", None),
    ("https://gateway.invalid:8443", None), ("https://legacy.invalid", "fake-legacy"),
])
def test_model_list_global_fallback_requires_bound_origin(monkeypatch, target, expected):
    """有显式绑定才可自动选密钥，未知主机保持无凭据请求而非泄露全局 Key。"""
    content = ("OPENAI_API_KEY=fake-global\nAI_PROFILE_UNIT_BASE_URL=https://gateway.invalid\n"
               "AI_PROFILE_UNIT_API_KEY=fake-profile\nLLM_BASE_URL=https://legacy.invalid\nLLM_API_KEY=fake-legacy\n")
    monkeypatch.setattr(profile_env, "_read_snapshot", lambda *a: SimpleNamespace(content=content))
    monkeypatch.setattr(profile_env.os, "environ", {})
    seen = []
    monkeypatch.setattr(profiles, "fetch_remote_models", lambda **kw: seen.append(kw) or [])
    profiles.fetch_models(FetchModelsIn(protocol="openai_responses", base_url=target), SimpleNamespace(), SimpleNamespace())
    assert seen[0]["api_key"] == expected


def test_environment_file_keeps_url_and_key_paired(monkeypatch):
    """文件覆盖进程变量时不能用进程中的旧地址发送文件中的新密钥。"""
    monkeypatch.setattr(profile_env, "_read_snapshot", lambda *a: SimpleNamespace(
        content="OPENAI_BASE_URL=https://file.invalid\nOPENAI_API_KEY=fake-file\n"))
    monkeypatch.setattr(profile_env.os, "environ", {"OPENAI_BASE_URL": "https://process.invalid", "OPENAI_API_KEY": "fake-process"})
    assert profile_env.resolve_env_api_key_for_url("https://process.invalid") is None
    assert profile_env.resolve_env_api_key_for_url("https://file.invalid") == "fake-file"


def test_legacy_llm_alias_requires_explicit_endpoint(monkeypatch):
    """历史 LLM_API_KEY 仅在明确配置的协议地址上继续工作。"""
    monkeypatch.setattr(profile_env, "_read_snapshot", lambda *a: SimpleNamespace(
        content="OPENAI_BASE_URL=https://legacy.invalid\nLLM_API_KEY=fake-legacy\n"))
    monkeypatch.setattr(profile_env.os, "environ", {})
    assert profile_env.resolve_env_api_key_for_url("https://legacy.invalid") == "fake-legacy"
    assert profile_env.resolve_env_api_key_for_url("https://api.openai.com") is None


def test_profile_connection_does_not_bind_unscoped_global_key(monkeypatch):
    """缺少全局地址时，不能把全局密钥当成任意历史档案的密钥。"""
    monkeypatch.setattr(profiles, "read_profile_env", lambda *a: SimpleNamespace(base_url=None, model=None, api_key=None))
    monkeypatch.setattr(profiles, "read_global_llm_env", lambda: SimpleNamespace(
        openai_base_url=None, anthropic_base_url=None, api_key="fake-global", model=None))
    profile = SimpleNamespace(id="old", protocol="openai_chat", base_url="https://unrelated.invalid", model="unit", encrypted_key=None)
    assert profiles._profile_connection(profile, allow_global_alias=True)[2] is None
