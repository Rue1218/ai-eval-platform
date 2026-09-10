"""完整端点经过真实 SDK 后仍保持原地址，覆盖同步探活与异步 Agent。"""

import asyncio

import httpx
import pytest
from shared.model_urls import model_request_url

from app.adapters import call_protocol
from app.config import settings
from app.llm.contracts import ModelConfig
from app.llm.resolver import build_adapter, resolve_request
from app.profile_env import read_profile_env, restore_snapshot, write_profile_env
from app.profile_reasoning import profile_reasoning
from tests.test_loop_llm_sdk import AnthropicAdapter, OpenAiAdapter, successful_wire


@pytest.mark.parametrize("protocol", ["openai_chat", "anthropic_messages"])
@pytest.mark.parametrize("url", ["https://unit.invalid/custom", "https://unit.invalid/v9/execute/?region=cn"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_full_url_reaches_transport_unchanged(monkeypatch, protocol, url, asynchronous):
    """只替换 HTTP transport，验证 SDK 未偷加资源路径或丢失查询与尾斜线。"""
    captured = []
    adapter_type = OpenAiAdapter if protocol == "openai_chat" else AnthropicAdapter

    def handler(request):
        """固定无密钥响应；检查最终 HTTP 目标。"""
        captured.append(str(request.url))
        if asynchronous:
            return httpx.Response(200, content=successful_wire(adapter_type),
                                  headers={"content-type": "text/event-stream"})
        payload = ({"choices": [{"message": {"content": "ok"}}]} if protocol == "openai_chat"
                   else {"content": [{"type": "text", "text": "ok"}]})
        return httpx.Response(200, json=payload)

    client_class = httpx.AsyncClient if asynchronous else httpx.Client

    class TransportClient(client_class):
        """保留客户端类型检查、事件钩子和关闭行为。"""

        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient" if asynchronous else "Client", TransportClient)
    if asynchronous:
        config = ModelConfig(protocol, url, "unit-model", api_key="unit", full_url=True,
                             reasoning_enabled=False)

        async def run():
            """走实际 resolver 与流式适配器。"""
            adapter, _ = build_adapter(config)
            try:
                return [chunk async for chunk in adapter.stream(resolve_request(config, messages=[]))]
            finally:
                await adapter.close()

        assert asyncio.run(run())
    else:
        assert call_protocol(protocol=protocol, base_url=url, full_url=True, model="unit-model",
                             api_key="unit", messages=[{"role": "user", "content": "ping"}]).text == "ok"
    assert captured == [url]


@pytest.mark.parametrize("url,expected", [
    ("https://open.bigmodel.cn/api/paas/v4", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
    ("https://ark.cn-beijing.volces.com/api/v3", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
    ("https://generativelanguage.googleapis.com/v1beta/openai/", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
    ("https://unit.invalid", "https://unit.invalid/v1/chat/completions"),
    ("https://unit.invalid/v1/chat/completions", "https://unit.invalid/v1/chat/completions"),
])
def test_base_url_preserves_supplier_version(url, expected):
    """供应商不同的版本段不能统一再追加 /v1。"""
    assert model_request_url(url, "openai_chat") == expected


def test_full_url_persists_per_profile_and_rolls_back(monkeypatch, tmp_path):
    """省略更新保留开关，显式关闭和事务回滚均不串档。"""
    monkeypatch.setattr(settings, "profile_env_file", str(tmp_path / "profiles.env"))
    url = "https://unit.invalid/run/?region=cn"
    write_profile_env("a", base_url=url, full_url=True)
    write_profile_env("b", full_url=False)
    write_profile_env("a", model="gpt-5.4")
    assert read_profile_env("a").full_url
    assert read_profile_env("a").base_url == url
    assert not read_profile_env("b").full_url
    snapshot = write_profile_env("a", full_url=False)
    assert not read_profile_env("a").full_url
    restore_snapshot(snapshot)
    assert read_profile_env("a").full_url
    assert profile_reasoning("openai_chat", url, "gpt-5.4", 8192, full_url=True)["allowed_efforts"]
