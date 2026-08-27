"""协议档 max_output_tokens 输出上限回归（API V1.49）。

覆盖：Agent 模型配置从协议档读取单回合输出上限、未配置回退 8192、
创建/更新 Schema 的范围校验。全部不依赖数据库。
"""

import pytest
from pydantic import ValidationError

from app.models import ProtocolProfile, Setting
from app.routers.ws import _MODEL_CONFIG_CACHE, _selected_model_config
from app.schemas import ProfileCreate, ProfileUpdate


class _Query:
    """吞掉链式调用并返回预置结果的最小查询桩。"""

    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDb:
    """按查询模型分发预置结果的会话桩。"""

    def __init__(self, results: dict):
        self._results = results

    def query(self, *args, **kwargs):
        key = args[0] if args else None
        return _Query(self._results.get(key))


def _agent_profile(profile_id: str, *, max_output_tokens=None) -> ProtocolProfile:
    """构造带 agent 用途的协议档实例（连接信息走 ORM 列回退路径）。"""
    return ProtocolProfile(
        id=profile_id,
        name="agent-core",
        protocol="openai_chat",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        usages=["agent"],
        max_output_tokens=max_output_tokens,
    )


def _db_for(profile: ProtocolProfile) -> _FakeDb:
    """组装 Setting(agent_profile_id) + 协议档的查询桩。"""
    return _FakeDb(
        {
            Setting: Setting(key="agent_profile_id", value=profile.id),
            ProtocolProfile: profile,
        }
    )


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """避免协议档配置快照缓存在用例之间串扰。"""
    _MODEL_CONFIG_CACHE.clear()
    yield
    _MODEL_CONFIG_CACHE.clear()


def test_agent_config_reads_profile_max_output_tokens() -> None:
    """协议档配置的输出上限必须进入 Agent 模型调用的 max_tokens。"""
    profile = _agent_profile("p-max-set", max_output_tokens=32768)
    config, _ = _selected_model_config(_db_for(profile))
    assert config.max_tokens == 32768


def test_agent_config_falls_back_to_8192_when_unset() -> None:
    """存量协议档未回填输出上限时保持旧行为（8192）。"""
    profile = _agent_profile("p-max-unset", max_output_tokens=None)
    config, _ = _selected_model_config(_db_for(profile))
    assert config.max_tokens == 8192


def test_profile_create_schema_defaults_and_bounds() -> None:
    """创建入参默认 8192，且拒绝超出 256–131072 范围的值。"""
    base = {
        "name": "gpt-test",
        "protocol": "openai_chat",
        "base_url": "https://api.example.com/v1",
        "model": "gpt-test",
    }
    assert ProfileCreate(**base).max_output_tokens == 8192
    with pytest.raises(ValidationError):
        ProfileCreate(**base, max_output_tokens=100)
    with pytest.raises(ValidationError):
        ProfileCreate(**base, max_output_tokens=200000)


def test_profile_update_schema_optional_and_bounds() -> None:
    """更新入参该字段可选；显式传值时同样受范围约束。"""
    assert ProfileUpdate().max_output_tokens is None
    assert ProfileUpdate(max_output_tokens=16384).max_output_tokens == 16384
    with pytest.raises(ValidationError):
        ProfileUpdate(max_output_tokens=0)
