"""供应商真实 SDK wire、档级隔离与默认值回归；不使用生产密钥。"""

import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.llm.contracts import ModelConfig
from app.llm.providers.anthropic import AnthropicAdapter
from app.llm.providers.catalog import detect_provider
from app.llm.providers.openai import OpenAiAdapter
from app.llm.resolver import build_adapter, resolve_request
from app.profile_reasoning import EFFORTS, profile_reasoning
from tests.test_loop_llm_sdk import install_transport, successful_wire

# 预期 wire 参数独立列出，避免测试调用待测函数生成期望值。
CASES = [
    ("zhipu", "https://open.bigmodel.cn/api/paas/v4", "glm-4.7", "openai_chat", "off"),
    ("deepseek", "https://api.deepseek.com/v1", "deepseek-v4-flash", "openai_chat", "off"),
    ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", "openai_chat", "off"),
    ("moonshot", "https://api.moonshot.cn/v1", "kimi-k2.5", "openai_chat", "off"),
    ("minimax", "https://api.minimaxi.com/v1", "MiniMax-M3", "openai_chat", "off"),
    ("nvidia", "https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3-super-120b-a12b", "openai_chat", "off"),
    ("volcengine", "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-1-8-251228", "openai_chat", "off"),
    ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "openai_chat", "off"),
    ("openai", "https://api.openai.com/v1", "gpt-5.4", "openai_chat", "off"),
    ("anthropic", "https://api.anthropic.com", "claude-sonnet-4-6", "anthropic_messages", "high"),
    ("deepseek", "https://api.deepseek.com/anthropic", "deepseek-v4-flash", "anthropic_messages", "off"),
    ("zhipu", "https://open.bigmodel.cn/api/anthropic", "glm-4.7", "anthropic_messages", "off"),
    ("moonshot", "https://api.moonshot.cn/anthropic", "kimi-k2.5", "anthropic_messages", "off"),
    ("qwen", "https://dashscope.aliyuncs.com/apps/anthropic", "qwen3.6-flash", "anthropic_messages", "off"),
    ("qwen", "https://dashscope.aliyuncs.com/apps/anthropic", "qwen3.8-flash", "anthropic_messages", "off"),
]


@pytest.mark.parametrize("provider,url,model,protocol,default", CASES)
@pytest.mark.parametrize("effort", EFFORTS)
def test_supplier_efforts_reach_real_sdk_body(monkeypatch, provider, url, model, protocol, default, effort):
    """每个可选档位经过官方 SDK 序列化，核对线上的字段位置与供应商方言。"""
    sdk = "anthropic" if protocol == "anthropic_messages" else "openai"
    adapter_type = AnthropicAdapter if sdk == "anthropic" else OpenAiAdapter
    payloads = []

    def handler(request):
        """捕获最终 HTTP 请求体，返回不含真实数据的 SSE。"""
        payloads.append(json.loads(request.content))
        return httpx.Response(200, content=successful_wire(adapter_type),
                              headers={"content-type": "text/event-stream"})

    install_transport(monkeypatch, sdk, handler)
    capability = profile_reasoning(protocol, url, model, 8192)
    assert capability["provider"] == provider
    assert capability["reasoning_effort"] == default
    assert capability["allowed_efforts"] == list(EFFORTS)
    config = ModelConfig(protocol, url, model, api_key="unit-test-only",
                         reasoning_enabled=effort != "off", reasoning_effort=effort)

    async def run():
        """真实 SDK 仅通过 MockTransport 通信，释放客户端。"""
        adapter, _ = build_adapter(config)
        try:
            return [chunk async for chunk in adapter.stream(resolve_request(config, messages=[]))]
        finally:
            await adapter.close()

    asyncio.run(run())
    assert len(payloads) == 1
    body = payloads[0]
    assert body["model"] == model
    enabled = effort != "off"
    if provider in {"deepseek", "zhipu", "moonshot", "volcengine"}:
        assert body["thinking"] == {"type": "enabled" if enabled else "disabled"}
    if provider == "deepseek" and enabled:
        expected = "high" if effort == "medium" else effort
        assert (body["output_config"]["effort"] if sdk == "anthropic" else body["reasoning_effort"]) == expected
    if provider in {"zhipu", "moonshot", "minimax", "nvidia", "qwen"}:
        assert "reasoning_effort" not in body
    if provider == "qwen":
        if sdk == "anthropic":
            assert body["thinking"]["type"] == ("enabled" if enabled else "disabled")
            if enabled:
                assert body["max_tokens"] + body["thinking"]["budget_tokens"] == 8192
        else:
            assert body["enable_thinking"] == enabled
            assert ("thinking_budget" in body) == enabled
    if provider == "minimax":
        assert body["reasoning_split"] is True
        assert body["thinking"]["type"] == ("adaptive" if enabled else "disabled")
    if provider == "nvidia":
        assert body["chat_template_kwargs"] == {"enable_thinking": enabled}
        assert "thinking" not in body
    if provider == "google":
        thinking = body["extra_body"]["google"]["thinking_config"]
        assert thinking["include_thoughts"] == enabled
        assert (thinking["thinking_budget"] > 0) == enabled
    if provider == "openai":
        assert body["reasoning_effort"] == {"off": "none", "max": "xhigh"}.get(effort, effort)
        assert body["max_completion_tokens"] == 8192
        assert "temperature" not in body
    if provider == "anthropic":
        assert body["thinking"]["type"] == ("adaptive" if enabled else "disabled")
        if enabled:
            assert body["output_config"]["effort"] == effort


@pytest.mark.parametrize("model,provider,protocol", [
    ("MiniMax-M2.5", "minimax", "openai_chat"),
    ("MiniMax-M2.5", "minimax", "anthropic_messages"),
    ("gemini-2.5-pro", "google", "openai_chat"),
    ("gemini-3.1-pro-preview", "google", "openai_chat"),
    ("kimi-k2-thinking", "moonshot", "openai_chat"),
])
def test_fixed_thinking_is_not_advertised_as_off(model, provider, protocol):
    """厂商无法关闭的型号必须如实展示，不能只在本地隐藏思考冒充 off。"""
    result = profile_reasoning(protocol, "https://unit.invalid", model, 8192)
    assert result["provider"] == provider
    assert "off" not in result["allowed_efforts"]
    assert result["reasoning_effort"] == "high"


def test_provider_endpoint_wins_over_hosted_model_brand():
    """托管 DeepSeek 不等于调用 DeepSeek 原厂；伪造域名后缀也不能命中。"""
    assert detect_provider("https://integrate.api.nvidia.com/v1", "deepseek-ai/deepseek-v4-pro", "openai_chat") == "nvidia"
    assert detect_provider("https://dashscope.aliyuncs.com/compatible-mode/v1", "glm-4.7", "openai_chat") == "qwen"
    assert detect_provider("https://nvidia.com.attacker.invalid/v1", "plain", "openai_chat") == "openai"


@pytest.mark.parametrize("protocol", ["openai_chat", "anthropic_messages"])
@pytest.mark.parametrize("model", ["glm-4.7", "deepseek-v4-flash"])
def test_bailian_hosted_models_use_model_specific_thinking(protocol, model):
    """百炼托管的 GLM 与 DeepSeek 使用 thinking，不能错发 Qwen enable_thinking。"""
    request = resolve_request(ModelConfig(protocol, "https://maas.aliyuncs.com/anthropic", model,
                                          reasoning_effort="max"), messages=[])
    assert request.provider == "qwen"
    assert request.provider_options["thinking"]["type"] == "enabled"
    assert "enable_thinking" not in request.provider_options


def test_minimax_reasoning_details_survive_real_sdk_replay(monkeypatch):
    """累计思考只显示新片段，原始结构在下一次工具结果回填时完整回传。"""
    from dataclasses import asdict

    from app.llm.loop_contracts import Done, ReasoningDelta
    from tests.test_loop_llm_sdk import sse

    config = ModelConfig("openai_chat", "https://api.minimax.io/v1", "MiniMax-M2.5",
                         api_key="unit", reasoning_effort="high")
    requests = []
    details = [{"type": "reasoning.text", "index": 0, "text": "先分析", "signature": "opaque"},
               {"type": "reasoning.text", "index": 0, "text": "先分析再回答", "signature": "opaque"}]

    def handler(request):
        """真实 SDK 解析带扩展字段的 SSE，第二轮检查提交的历史结构。"""
        requests.append(json.loads(request.content))
        base = {"id": "m", "object": "chat.completion.chunk", "created": 1, "model": config.model}
        chunks = [sse({**base, "choices": [{"index": 0, "delta": {"reasoning_details": [detail]},
                                           "finish_reason": None}]}) for detail in details]
        chunks.append(sse({**base, "choices": [{"index": 0, "delta": {"content": "完成"},
                                                "finish_reason": "stop"}]}))
        return httpx.Response(200, content=b"".join(chunks) + b"data: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    install_transport(monkeypatch, "openai", handler)

    async def scenario():
        """使用输出的协议状态重建下一请求，模拟工具调用后的历史组。"""
        adapter, _ = build_adapter(config)
        try:
            chunks = [chunk async for chunk in adapter.stream(resolve_request(config, messages=[]))]
            assert "".join(chunk.text for chunk in chunks if isinstance(chunk, ReasoningDelta)) == "先分析再回答"
            done = next(chunk for chunk in chunks if isinstance(chunk, Done))
            messages = [{"role": "assistant", "content": "", "protocol_state": asdict(done.protocol_state),
                         "tool_calls": [{"id": "c1", "name": "read", "args": {}}]},
                        {"role": "tool", "tool_call_id": "c1", "name": "read", "content": "result"}]
            _ = [chunk async for chunk in adapter.stream(resolve_request(config, messages=messages))]
            assert requests[-1]["messages"][0]["reasoning_details"] == [details[-1]]
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_authorized_turn_uses_profile_default_not_legacy_setting(tmp_path, monkeypatch):
    """全局 high 不覆盖新档默认 off；显式回合参数优先且不修改已保存的档位。"""
    from app.agent.loop_wiring import authorized_profile
    from app.routers import profiles
    from tests.test_loop_profile_selection import _Db, _profile

    monkeypatch.setattr(settings, "profile_env_file", str(tmp_path / ".env"))
    row = _profile("p")
    db = _Db([row], {"agent_profile_id": "p", "agent_reasoning": {"enabled": True, "effort": "high"}})
    monkeypatch.setattr(profiles, "_profile_connection", lambda *args, **kwargs: (row.base_url, row.model, "unit"))
    assert not authorized_profile(db, {})[0].config.reasoning_enabled
    assert authorized_profile(db, {"reasoning_effort": "max"})[0].config.reasoning_effort == "max"
    assert not authorized_profile(db, {})[0].config.reasoning_enabled
