"""受控 Streamable HTTP provider 测试；不连接真实媒体服务或上游模型。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.harness.execution.mcp.streamable_provider import StreamableHttpProvider


class _AsyncContext:
    """最小异步上下文管理器，模拟 MCP 传输与会话。"""

    def __init__(self, value) -> None:
        self._value = value

    async def __aenter__(self):
        """返回预置测试对象。"""
        return self._value

    async def __aexit__(self, *_args) -> None:
        """测试桩无需额外清理。"""


@pytest.mark.asyncio
async def test_streamable_provider_initializes_calls_and_validates_output(monkeypatch) -> None:
    """远程目录调用必须先 initialize，且仅接收声明的结构化输出。"""
    events: list[str] = []

    class FakeSession:
        """记录 MCP 生命周期，不包含网络或凭据。"""

        def __init__(self, _read, _write) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def initialize(self) -> None:
            events.append("initialize")

        async def call_tool(self, name: str, arguments: dict):
            events.append(f"call:{name}:{arguments['prompt']}")
            return SimpleNamespace(isError=False, structuredContent={"status": "succeeded", "image_urls": ["https://result.example/a.png"]})

    monkeypatch.setattr(
        "app.harness.execution.mcp.streamable_provider.streamablehttp_client",
        lambda *_args, **_kwargs: _AsyncContext(("read", "write", lambda: None)),
    )
    monkeypatch.setattr("app.harness.execution.mcp.streamable_provider.ClientSession", FakeSession)

    provider = StreamableHttpProvider("http://media-mcp:8002/mcp", request_timeout_s=30)
    result = await provider.invoke(
        tool_id="media.generation.image.generate",
        tool_name="image.generate",
        arguments={"prompt": "一只猫"},
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}, "image_urls": {"type": "array", "items": {"type": "string"}}},
            "required": ["status"],
        },
        call_id="call-1",
    )

    assert events == ["initialize", "call:image.generate:一只猫"]
    assert result.ok is True
    assert result.call_id == "call-1"
    assert result.data["image_urls"] == ["https://result.example/a.png"]
