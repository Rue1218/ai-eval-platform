"""不透明历史状态必须绑定授权连接，切换后仅保留可迁移消息。"""

from dataclasses import asdict, replace

import pytest

from app.agent.loop_wiring import _drop_incompatible_protocol_state
from app.llm.contracts import ModelConfig
from app.llm.providers.common import make_state
from app.llm.resolver import AuthorizedProfileSnapshot, resolve_request


@pytest.mark.parametrize("change", ["endpoint", "key", "profile", "version"])
def test_switch_connection_drops_opaque_state(change):
    """同模型名的端点、凭据或档案变化触发已有迁移流程，正文和工具结果不丢失。"""
    config = ModelConfig("openai_responses", "https://a.invalid", "unit", api_key="fake-a", reasoning_enabled=False)
    original = AuthorizedProfileSnapshot(config, profile_id="a", profile_version="1")
    request = resolve_request(original, messages=[])
    state = make_state(request, request.provider, request.protocol, [
        {"type": "reasoning", "id": "rs_a", "summary": [], "encrypted_content": "opaque-a"},
    ])
    changed = {
        "endpoint": replace(original, config=replace(config, base_url="https://b.invalid")),
        "key": replace(original, config=replace(config, api_key="fake-b")),
        "profile": replace(original, profile_id="b"),
        "version": replace(original, profile_version="2"),
    }[change]
    messages = [{"role": "assistant", "content": "已计算", "protocol_state": asdict(state)}]
    next_request = resolve_request(changed, messages=messages)
    migrated, indices = _drop_incompatible_protocol_state(next_request)
    assert request.compatibility_key != next_request.compatibility_key
    assert indices == [0]
    assert migrated.messages == [{"role": "assistant", "content": "已计算"}]
    assert "protocol_state" in messages[0]


def test_same_connection_keeps_state_across_effort_changes():
    """调整思考强度不改变连接身份，凭据不出现在可持久化请求中。"""
    config = ModelConfig("openai_responses", "https://a.invalid", "gpt-5.6-terra", api_key="fake-secret",
                         reasoning_enabled=True, reasoning_effort="low")
    first = resolve_request(config, messages=[])
    second = resolve_request(replace(config, reasoning_effort="high"), messages=[])
    assert first.compatibility_key == second.compatibility_key
    assert "fake-secret" not in repr(asdict(first))
    assert "a.invalid" not in repr(asdict(first))
