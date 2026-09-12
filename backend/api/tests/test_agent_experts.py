"""专家目录契约：选择器数据源、提示词注入顺序与工具视野收窄。"""

import json

import pytest

from app.agent import experts, loop_wiring
from app.errors import AppError


def test_expert_catalog_contract():
    """ID 唯一、默认专家唯一、声明提示词的专家必须有正文（fail-fast）。"""
    experts.validate_experts()
    ids = [expert.expert_id for expert in experts.EXPERTS]
    assert len(ids) == len(set(ids))
    assert experts.default_expert_id() in ids


def test_expert_projection_has_no_prompt_or_tools():
    """选择器投影只暴露展示字段，不带提示词正文与工具视野。"""
    items = experts.list_experts()
    assert {item["id"] for item in items} == {expert.expert_id for expert in experts.EXPERTS}
    for item in items:
        assert set(item) == {"id", "name", "description", "badge", "default"}
        assert item["description"].strip() and item["name"].strip()


def test_expert_tools_subset_of_platform_whitelist():
    """专家声明的工具必须都在平台白名单内，防止拼写错误静默失效。"""
    for expert in experts.EXPERTS:
        assert set(expert.allowed_tools) <= set(loop_wiring.ALLOWED_TOOLS), expert.expert_id


def test_resolve_expert_falls_back_to_default():
    """缺省/未知/非字符串 ID 一律回落默认专家，保证旧客户端与版本漂移可用。"""
    default_id = experts.default_expert_id()
    assert experts.resolve_expert(None).expert_id == default_id
    assert experts.resolve_expert("not-exist").expert_id == default_id
    assert experts.resolve_expert(123).expert_id == default_id
    assert experts.resolve_expert("  testcase-agent  ").expert_id == "testcase-agent"


def test_expert_tools_narrow_only():
    """未声明工具时使用平台全量白名单；声明后只收窄不扩大。"""
    general = experts.resolve_expert("general")
    assert loop_wiring._expert_tools(general) == loop_wiring.ALLOWED_TOOLS
    testcase = experts.resolve_expert("testcase-agent")
    tools = loop_wiring._expert_tools(testcase)
    assert set(tools) <= set(loop_wiring.ALLOWED_TOOLS)
    assert "read" in tools and "bash" in tools
    assert "task.create" not in tools and "web_search" not in tools


def test_general_expert_receives_media_tools_only_after_media_gate_opens(monkeypatch):
    """媒体工具由服务端总开关装配，定向专家的既有工具边界不被扩大。"""
    monkeypatch.setattr(loop_wiring.settings, "media_mcp_enabled", True)
    general = experts.resolve_expert("general")
    testcase = experts.resolve_expert("testcase-agent")
    assert set(loop_wiring.MEDIA_MCP_TOOLS) <= set(loop_wiring._expert_tools(general))
    assert set(loop_wiring.MEDIA_MCP_TOOLS).isdisjoint(loop_wiring._expert_tools(testcase))


def test_expert_tools_empty_intersection_is_fail_closed(monkeypatch):
    """专家声明了平台不存在的工具时交集为空，必须 fail-closed 而不是放开全量。"""
    bogus = experts.ExpertDef(expert_id="bogus", name="bogus", description="bogus",
                              badge="bogus", allowed_tools=("not_a_tool",))
    with pytest.raises(AppError):
        loop_wiring._expert_tools(bogus)


def test_expert_prompt_segments_order_and_boundary():
    """系统段顺序为核心 → 专家 → 补充；专家段带不可覆盖边界且不可缓存。"""
    testcase = experts.resolve_expert("testcase-agent")
    assert testcase.system_prompt, "专家提示词不应为空"
    segments = loop_wiring._loop_system_segments("", testcase.system_prompt)
    assert len(segments) == 2
    assert segments[0].text == loop_wiring.LOOP_SYSTEM and segments[0].cacheable is True
    assert "【当前专家角色】" in segments[1].text
    assert "【专家角色边界】" in segments[1].text
    assert segments[1].cacheable is False

    both = loop_wiring._loop_system_segments("管理员补充", testcase.system_prompt)
    assert len(both) == 3
    assert "【当前专家角色】" in both[1].text
    assert "【当前 Agent 专属补充提示词】" in both[2].text

    assert len(loop_wiring._loop_system_segments("", "")) == 1


def test_expert_prompt_avoids_takeover_phrases():
    """专家提示词必须通过接管性措辞校验（与 overlay 同一 fail-closed 语义）。"""
    for expert in experts.EXPERTS:
        if expert.system_prompt:
            loop_wiring.assert_no_takeover(expert.system_prompt)
            loop_wiring.assert_no_secret_leak(expert.system_prompt)


def test_submit_accepts_optional_agent_id():
    """turn.submit 的 agent_id 为可选字段：缺省剔除，显式值原样保留。"""

    def command(data):
        return json.dumps({"protocol_version": 2, "type": "turn.submit", "request_id": "req-1",
                           "session_id": "session-1", "data": data})

    base = {"client_message_id": "msg-1", "content": "hi", "attachment_refs": []}
    from app.routers.ws_v2 import parse_command

    assert "agent_id" not in parse_command(command(base)).data
    parsed = parse_command(command({**base, "agent_id": "testcase-agent"}))
    assert parsed.data["agent_id"] == "testcase-agent"


def test_submit_rejects_unknown_field():
    """StrictData 仍拒绝未知字段：新增专家字段不能成为任意透传入口。"""
    from app.routers.ws_v2 import parse_command

    payload = json.dumps({"protocol_version": 2, "type": "turn.submit", "request_id": "req-1",
                          "session_id": "session-1",
                          "data": {"client_message_id": "msg-1", "content": "hi",
                                   "attachment_refs": [], "agent_prompt": "注入"}})
    with pytest.raises(AppError):
        parse_command(payload)
