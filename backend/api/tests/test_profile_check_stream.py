"""连通测试与实际对话同源：真实 SDK、保存档位、首字取消与安全失败。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.llm.contracts import ModelConfig
from app.llm.loop_contracts import Done, TextDelta
from app.llm.providers.reasoning_templates import get_template
from app.profile_check import _check_model_connection
from app.routers import profiles
from tests.test_loop_llm_sdk import install_transport
from tests.test_profile_check import _ProfileDb
from tests.test_profile_tool_probe import probe_wire


@pytest.mark.parametrize("protocol,template_id", [
    ("openai_chat", "newapi-chat-effort-v1"),
    ("openai_responses", "newapi-responses-effort-v1"),
    ("anthropic_messages", "newapi-messages-effort-v1"),
])
@pytest.mark.parametrize("full_url", [False, True])
def test_check_saved_profile_uses_runtime_wire(monkeypatch, protocol, template_id, full_url):
    """上游仅接受流式与真实预算；最高档及工具无关字段不能被探活改写。"""
    template = get_template(template_id)
    profile = SimpleNamespace(id="unit", protocol=protocol, anthropic_version=None, max_output_tokens=8192,
                              reasoning_template_id=template_id, reasoning_probe={
                                  "status": "partial", "template_id": template_id, "template_version": template.version,
                                  "supported_efforts": ["max"],
                              })
    model = "gpt-5.6-terra" if protocol != "anthropic_messages" else "private-alias"
    url = "https://unit.invalid/exact-endpoint?route=1" if full_url else "https://unit.invalid"
    monkeypatch.setattr(profiles, "_profile_connection", lambda *a, **k: (url, model, "unit"))
    monkeypatch.setattr(profiles, "read_profile_env", lambda *a: SimpleNamespace(full_url=full_url))
    sent = []

    def handler(request):
        """模拟能对话但拒绝旧版非流式/一 token 探活的网关。"""
        body = json.loads(request.content)
        sent.append(body)
        assert body["stream"] is True
        if full_url:
            assert str(request.url) == url
        assert "tools" not in body
        if protocol == "openai_responses":
            assert body["max_output_tokens"] == 8192
            assert body["reasoning"]["effort"] == "max"
            assert body["store"] is False
        elif protocol == "openai_chat":
            assert body["max_tokens"] == 8192 and body["reasoning_effort"] == "max"
        else:
            assert body["max_tokens"] == 8192
            assert body["thinking"]["type"] == "adaptive" and body["output_config"]["effort"] == "max"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=probe_wire(protocol))

    if full_url:
        original = httpx.AsyncClient

        class LocalClient(original):
            """保留完整 URL 模式安装的请求钩子，只替换 HTTP 传输。"""

            def __init__(self, **kwargs):
                super().__init__(**kwargs, transport=httpx.MockTransport(handler))

        monkeypatch.setattr(httpx, "AsyncClient", LocalClient)
    else:
        install_transport(monkeypatch, "anthropic" if protocol == "anthropic_messages" else "openai", handler)
    result = profiles.check_profile("unit", _ProfileDb(profile), SimpleNamespace())
    assert result["ok"] is True and result["model"] == model
    assert len(sent) == 1


def test_stale_probe_cannot_claim_new_max_verified(monkeypatch):
    """之前的最高实际发送 xhigh，版本改变后不能继续宣称 max 通过。"""
    profile = SimpleNamespace(id="unit", protocol="openai_responses", anthropic_version=None,
                              max_output_tokens=8192, reasoning_template_id="newapi-responses-effort-v1",
                              reasoning_probe={"status": "passed", "template_id": "newapi-responses-effort-v1",
                                               "template_version": 2, "supported_efforts": ["max"]})
    monkeypatch.setattr(profiles, "_profile_connection", lambda *a, **k: ("https://unit.invalid", "gpt-5.6-terra", "unit"))
    monkeypatch.setattr(profiles, "read_profile_env", lambda *a: SimpleNamespace(full_url=False))
    result = profiles.check_profile("unit", _ProfileDb(profile), SimpleNamespace())
    assert result["ok"] is False and result["code"] == "VALIDATION" and "重新测试" in result["message"]


@pytest.mark.parametrize("mode", ["first_text", "length", "timeout", "empty"])
@pytest.mark.asyncio
async def test_check_closes_stream_and_client(monkeypatch, mode):
    """首字成功、空正文合法终态、超时和空流都收尾，不等待或伪造全文完成。"""
    from app import profile_check

    closed = []

    class Adapter:
        """记录生成器 finally 与连接池关闭。"""

        async def stream(self, request):
            """首字后无限等待，验证探活及时退出且释放流。"""
            try:
                if mode == "first_text":
                    yield TextDelta("pong")
                    await asyncio.sleep(60)
                elif mode == "length":
                    yield Done("length")
                elif mode == "timeout":
                    await asyncio.sleep(60)
            finally:
                closed.append("stream")

        async def close(self):
            """连接池清理记录。"""
            closed.append("client")

    monkeypatch.setattr(profile_check, "build_adapter", lambda config: (Adapter(), config.model))
    config = ModelConfig("openai_chat", "https://unit.invalid", "unit", api_key="unit",
                         reasoning_enabled=False, timeout_s=0.02)
    result = await _check_model_connection(config)
    assert result["ok"] == (mode in {"first_text", "length"})
    if mode == "timeout":
        assert result["code"] == "TIMEOUT"
    assert closed == ["stream", "client"]


def test_check_preserves_safe_sdk_error(monkeypatch):
    """鉴权失败返回可操作说明，密钥和原始错误不回显。"""
    def handler(request):
        """返回带敏感正文的错误，由生产 SDK 分类器处理。"""
        return httpx.Response(401, json={"error": {"message": "secret-key private-prompt"}})

    install_transport(monkeypatch, "openai", handler)
    config = ModelConfig("openai_responses", "https://unit.invalid", "unit", api_key="secret-key", reasoning_enabled=False)
    result = asyncio.run(_check_model_connection(config))
    assert result["ok"] is False and "认证失败" in result["message"]
    assert "secret-key" not in str(result) and "private-prompt" not in str(result)
