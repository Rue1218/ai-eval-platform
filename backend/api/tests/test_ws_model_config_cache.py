"""回归测试：协议档配置缓存只存纯数据快照（修复 DetachedInstanceError 生产事故）。

背景：b2cc857 曾把 detach 的 ProtocolProfile ORM 实例放入 _MODEL_CONFIG_CACHE；
写入缓存的回合 commit（expire_on_commit 使属性过期）并 close Session 后，
命中缓存的回合访问属性时抛 DetachedInstanceError，被 ws._run_turn 兜底为
INTERNAL「Agent 调用失败」，表现为 Agent 回合随机 50ms 极速失败（生产事故）。
修复后缓存只存 _ProfileSnapshot 纯数据，本用例锁死该行为。
"""

from unittest.mock import MagicMock

import pytest

from app.routers import ws


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """每个用例前后清空缓存，避免用例间互相污染。"""
    ws._MODEL_CONFIG_CACHE.clear()
    yield
    ws._MODEL_CONFIG_CACHE.clear()


def _fake_db(profile: MagicMock) -> MagicMock:
    """构造按查询顺序返回 setting → profile → reasoning 的 mock session。"""
    setting = MagicMock()
    setting.value = "p1"
    reasoning = MagicMock()
    reasoning.value = {"enabled": True, "effort": "medium"}
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        setting,
        profile,
        reasoning,
    ]
    return db


def _fake_profile() -> MagicMock:
    """模拟协议档行（字段与 ProtocolProfile 一致）。"""
    p = MagicMock()
    p.id = "p1"
    p.name = "Alibaba Qwen (qwen-plus)"
    p.model = "qwen3.6-flash"
    p.base_url = "https://dashscope.aliyuncs.com"
    p.protocol = "openai_chat"
    p.usages = ["agent"]
    p.anthropic_version = None
    p.max_output_tokens = 8192
    p.tool_call_mode = "native"
    return p


def test_cache_holds_snapshot_not_orm(monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存值必须是纯数据快照，禁止出现 ORM 实例（事故根因）。"""
    monkeypatch.setattr(
        ws,
        "_profile_connection",
        lambda profile, allow_global_alias=False: ("https://x", "qwen", "key"),
    )
    db = _fake_db(_fake_profile())
    config, snapshot = ws._selected_model_config(db)
    cached_config, cached_snapshot = ws._MODEL_CONFIG_CACHE["p1"][1]
    assert isinstance(cached_snapshot, ws._ProfileSnapshot)
    assert not isinstance(cached_snapshot, ws.ProtocolProfile)
    assert isinstance(snapshot, ws._ProfileSnapshot)
    assert cached_config is config


def test_cache_hit_after_session_close_no_detached_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟事故生命周期：首回合写缓存后 commit+close，后续命中缓存访问属性不得抛错。"""
    monkeypatch.setattr(
        ws,
        "_profile_connection",
        lambda profile, allow_global_alias=False: ("https://x", "qwen", "key"),
    )
    db1 = _fake_db(_fake_profile())
    config, snapshot = ws._selected_model_config(db1)
    # 模拟 _run_turn 生命周期：commit（expire_on_commit 使属性过期）+ close（detach）
    db1.commit()
    db1.close()
    # 第二回合：新 session 命中缓存（TTL 15s 内）
    db2 = _fake_db(_fake_profile())
    config2, snapshot2 = ws._selected_model_config(db2)
    assert snapshot2 is snapshot  # 命中缓存返回同一对象
    # 访问快照字段不得抛 DetachedInstanceError
    assert snapshot2.model == "qwen3.6-flash"
    assert snapshot2.name == "Alibaba Qwen (qwen-plus)"
    assert snapshot2.id == "p1"
    assert snapshot2.protocol == "openai_chat"
    assert config2.api_key == "key"


def test_cache_miss_reloads_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存过期（TTL 15s）后重新查库构造新快照。"""
    monkeypatch.setattr(
        ws,
        "_profile_connection",
        lambda profile, allow_global_alias=False: ("https://x", "qwen", "key"),
    )
    db1 = _fake_db(_fake_profile())
    ws._selected_model_config(db1)
    # 直接改缓存过期时间，模拟 15s TTL 到期
    ws._MODEL_CONFIG_CACHE["p1"] = (0.0, ws._MODEL_CONFIG_CACHE["p1"][1])
    db2 = _fake_db(_fake_profile())
    config2, snapshot2 = ws._selected_model_config(db2)
    assert isinstance(snapshot2, ws._ProfileSnapshot)
    assert snapshot2.model == "qwen3.6-flash"
