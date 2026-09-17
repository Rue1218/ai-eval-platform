"""New API 网关三协议的实际 SDK 请求、工具思考回放与已验证能力投影。"""

import asyncio
import json

import httpx
import pytest

from app import profile_tool_probe
from app.llm.contracts import ModelConfig
from app.llm.providers.options import request_options
from app.llm.providers.reasoning_templates import list_templates
from app.llm.resolver import resolve_request
from app.profile_reasoning import profile_reasoning
from tests.test_loop_llm_sdk import install_transport, sse
from tests.test_profile_tool_probe import probe_wire

PROTOCOLS = ("openai_chat", "openai_responses", "anthropic_messages")
MODELS = ("gpt-5.6-terra", "gpt-5.4", "gpt-5.1", "claude-sonnet-4-6", "gemini-2.5-flash", "qwen3.6-flash", "private-alias")
EFFORTS = ("off", "low", "medium", "high", "max")


def thinking_tool_wire(protocol):
    """在真实工具流中加入网关推理内容，覆盖原厂品牌无法表达的回放场景。"""
    raw = probe_wire(protocol, call=True)
    if protocol == "openai_responses":
        return raw
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith(b"data: {")]
    if protocol == "openai_chat":
        events[0]["choices"][0]["delta"]["reasoning_content"] = "gateway reasoning"
        return b"".join(sse(event) for event in events) + b"data: [DONE]\n\n"
    for event in events:
        if "index" in event:
            event["index"] += 1
    events[1:1] = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "gateway reasoning"}},
        {"type": "content_block_stop", "index": 0},
    ]
    return b"".join(sse(event, named=True) for event in events)


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("effort", EFFORTS)
def test_newapi_sdk_reasoning_and_tool_roundtrip(monkeypatch, protocol, model, effort):
    """三种入口都发送网关字段；工具回填保留推理内容，任意别名不降为普通模式。"""
    template = list_templates("newapi", protocol, model)[0]
    assert template.id.startswith("newapi-") and template.mode == "effort"
    assert all(item.id.startswith("newapi-") for item in list_templates("newapi", protocol, model))
    sent = []
    monkeypatch.setattr(profile_tool_probe.secrets, "token_hex", lambda size: "request-token" if size == 8 else "result-token")

    def handler(request):
        """检查 SDK 序列化后的 JSON，而非仅检查模板中间选项。"""
        payload = json.loads(request.content)
        sent.append(payload)
        assert payload["model"] == model and "temperature" not in payload
        expected = "none" if effort == "off" else effort
        if effort == "max" and model.startswith("gpt-"):
            expected = "max" if model == "gpt-5.6-terra" else "high" if model == "gpt-5.1" else "xhigh"
        if protocol == "openai_chat":
            assert payload["reasoning_effort"] == expected
            assert payload["max_tokens"] == 8192
            assert not {"thinking", "enable_thinking", "thinking_budget", "extra_body", "max_completion_tokens"} & payload.keys()
        elif protocol == "openai_responses":
            assert payload["reasoning"]["effort"] == expected
            assert payload["max_output_tokens"] == 8192 and payload["store"] is False
            assert "reasoning_effort" not in payload
        else:
            assert payload["thinking"] == {"type": "disabled" if effort == "off" else "adaptive"}
            assert payload.get("output_config") == (None if effort == "off" else {"effort": effort})
            assert payload["max_tokens"] == 8192
        content = thinking_tool_wire(protocol) if len(sent) == 1 else probe_wire(protocol)
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    install_transport(monkeypatch, "anthropic" if protocol == "anthropic_messages" else "openai", handler)
    config = ModelConfig(protocol, "https://gateway.invalid/v1", model, api_key="unit", max_tokens=8192,
                         reasoning_template_id=template.id, reasoning_effort=effort if effort != "off" else "medium",
                         reasoning_enabled=effort != "off", reasoning_allowed_efforts=EFFORTS)
    assert asyncio.run(profile_tool_probe.probe_tool_roundtrip(config))["status"] == "passed"
    assert len(sent) == 2
    if protocol == "openai_chat":
        assert sent[1]["messages"][-2]["reasoning_content"] == "gateway reasoning"
    elif protocol == "anthropic_messages":
        assert sent[1]["messages"][-2]["content"][0]["thinking"] == "gateway reasoning"
    else:
        assert sent[1]["input"][1]["encrypted_content"] == "opaque"


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("model", MODELS)
def test_newapi_saved_capabilities_require_matching_probe(protocol, model):
    """保存后只开放通过探测的强度，旧原厂模板回执不能使网关模板直接通过。"""
    template = list_templates("newapi", protocol, model)[0]
    probe = {"status": "partial", "template_id": template.id, "template_version": template.version,
             "supported_efforts": ["low", "high"]}
    args = (protocol, "https://gateway.invalid/v1", model, 8192)
    result = profile_reasoning(*args, reasoning_template_id=template.id, reasoning_probe=probe)
    assert result["allowed_efforts"] == ["low", "high"]
    assert result["reasoning_effort"] == "high"
    probe["template_id"] = "openai-reasoning-effort-v1"
    assert profile_reasoning(*args, reasoning_template_id=template.id, reasoning_probe=probe)["allowed_efforts"] == []


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_newapi_plain_model_has_no_reasoning_fields(protocol):
    """普通模式保留供应商身份，但不向无思考能力的模型发送 none 等字段。"""
    config = ModelConfig(protocol, "https://gateway.invalid/v1", "private-alias", reasoning_enabled=False,
                         reasoning_template_id="newapi-no-reasoning-v1")
    request = resolve_request(config, messages=[])
    wire = request_options(request, request.provider, protocol)
    assert not {"reasoning", "reasoning_effort", "thinking", "extra_body"} & wire.keys()


@pytest.mark.parametrize("effort", EFFORTS)
def test_newapi_messages_budget_fallback(effort):
    """旧通道预算模板与输出上限一致，关闭时不残留预算或强度。"""
    config = ModelConfig("anthropic_messages", "https://gateway.invalid/v1", "private-alias", max_tokens=8192,
                         reasoning_enabled=effort != "off", reasoning_effort=effort if effort != "off" else "medium",
                         reasoning_template_id="newapi-messages-budget-v1")
    request = resolve_request(config, messages=[])
    wire = request_options(request, request.provider, request.protocol)
    if effort == "off":
        assert wire["thinking"] == {"type": "disabled"}
    else:
        assert 1024 <= wire["thinking"]["budget_tokens"] < wire["max_tokens"]


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("status,error_type,expected,label", [
    (401, "new_api_error", "AUTH_FAILED", "鉴权失败"),
    (403, "new_api_error", "AUTH_FAILED", "鉴权失败"),
    (404, "new_api_error", "MODEL_OR_ENDPOINT_UNAVAILABLE", "模型或接口不可用"),
    (429, "new_api_error", "RATE_LIMITED", "限流"),
    (429, "insufficient_quota", "BUDGET_EXCEEDED", "额度不足"),
    (502, "new_api_error", "UPSTREAM_UNAVAILABLE", "上游通道暂时不可用"),
    (400, "new_api_error", "PARAMETERS_REJECTED", "请求参数或协议被拒绝"),
])
def test_probe_failure_keeps_safe_actionable_category(monkeypatch, protocol, status, error_type, expected, label):
    """真实 SDK 错误经过探测后仍有具体分类，任何上游原文都不能回显。"""
    from app.profile_probe import _probe_one
    from app.routers.profiles import _probe_message

    def handler(request):
        """根域名自动补版本路径；带秘密的上游错误必须在分类边界被丢弃。"""
        expected_path = {"openai_chat": "/v1/chat/completions", "openai_responses": "/v1/responses",
                         "anthropic_messages": "/v1/messages"}[protocol]
        assert request.url.path == expected_path
        return httpx.Response(status, json={"error": {"type": error_type, "message": "private-key secret-prompt"}})

    install_transport(monkeypatch, "anthropic" if protocol == "anthropic_messages" else "openai", handler)
    template = list_templates("newapi", protocol, "gpt-5.6-terra")[0]
    config = ModelConfig(protocol, "https://gateway.invalid", "gpt-5.6-terra", api_key="unit",
                         reasoning_template_id=template.id, reasoning_enabled=True)
    result = asyncio.run(_probe_one(config, requires_reasoning_evidence=True))
    assert result == (False, None, expected)
    message = _probe_message({"status": "failed", "attempts": [{"ok": False, "error_code": result[2]}]})
    assert label in message and "未保存" in message
    assert "private-key" not in message and "secret-prompt" not in message


@pytest.mark.parametrize("event_type", ["response.reasoning_text.delta", "response.reasoning_summary_text.delta"])
def test_responses_probe_recognizes_both_reasoning_events(monkeypatch, event_type):
    """网关未报告 reasoning_tokens 时，标准思考增量仍是有效证据。"""
    from app.profile_probe import _probe_one
    from tests.test_responses_protocol import completed, wire

    def handler(request):
        """取消推理用量，只用标准增量证明证据识别路径。"""
        data = completed()
        data["output"][0]["content"][0]["text"] = "answer"
        data["usage"]["output_tokens_details"]["reasoning_tokens"] = 0
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire([
            {"type": event_type, "delta": "reasoning evidence", "item_id": "rs_1", "output_index": 0,
             "content_index": 0, "summary_index": 0, "sequence_number": 1},
            {"type": "response.output_text.delta", "delta": "answer", "sequence_number": 2},
            {"type": "response.completed", "response": data, "sequence_number": 3},
        ]))

    install_transport(monkeypatch, "openai", handler)
    config = ModelConfig("openai_responses", "https://unit.invalid", "gpt-5.6-terra", api_key="unit",
                         reasoning_enabled=True, reasoning_template_id="newapi-responses-effort-v1")
    assert asyncio.run(_probe_one(config, requires_reasoning_evidence=True)) == (True, "reasoning_delta", None)


@pytest.mark.parametrize("model,expected", [
    ("gpt-5.6", "max"), ("gpt-5.6-sol", "max"), ("gpt-5.6-terra", "max"),
    ("gpt-5.6-luna-2026-09-01", "max"), ("openai/gpt-5.6-terra", "max"),
    ("gpt-5.5", "xhigh"), ("gpt-5.4", "xhigh"), ("gpt-5.1", "high"), ("o3", "high"),
])
def test_openai_max_effort_is_model_specific(model, expected):
    """最高档不能一概降成 xhigh，已有旧型号映射保持兼容。"""
    from shared.reasoning import openai_effort

    assert openai_effort(model, "max") == expected
    assert openai_effort(model, "high") == "high"
