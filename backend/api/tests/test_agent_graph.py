"""LangGraph Agent 图单测；不触碰 WebSocket、数据库或真实模型服务。"""

import asyncio

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.harness.memory import SerializableRequest
from app.llm import ModelRequest, ModelResponse, ModelStreamEvent


def _request() -> SerializableRequest:
    """构造 Agent 图入口的可序列化请求投影。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": "你好"},),
    )


class _FakeGateway:
    """仅实现 Agent 图依赖的最小网关接口。"""

    def invoke(self, _request: ModelRequest, config: dict | None = None) -> ModelResponse:
        """返回固定的非流式响应。"""
        return ModelResponse(text="非流式答案", latency_ms=1)

    def stream(self, _request: ModelRequest, config: dict | None = None):
        """返回推理/正文/completed 事件，模拟模型网关输出。"""
        return iter(
            [
                ModelStreamEvent(kind="reasoning", text="先判断"),
                ModelStreamEvent(kind="content", text="流式答案"),
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text="流式答案", latency_ms=2),
                ),
            ]
        )


def test_agent_invoke_uses_langgraph_node() -> None:
    """Agent 非流式入口通过 LangGraph 节点调用注入网关。"""
    response = LangGraphAgent(_FakeGateway()).invoke(_request())

    assert response.text == "流式答案"


def test_agent_astream_projects_gateway_events() -> None:
    """Agent 流式入口保留推理/正文瞬态帧，并以 pending_events 收尾。"""
    async def collect() -> list[tuple[str, dict]]:
        return [
            event
            async for event in LangGraphAgent(_FakeGateway()).astream(_request())
        ]

    events = asyncio.run(collect())

    custom = [chunk for mode, chunk in events if mode == "custom"]
    assert [(chunk["kind"], chunk["text"]) for chunk in custom] == [
        ("reasoning", "先判断"),
        ("content", "流式答案"),
    ]
    kinds = [
        event["kind"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    assert kinds == ["assistant_message", "response.completed"]
    # 收尾响应经 response 投影（可序列化）
    responses = [
        value.get("response")
        for mode, chunk in events
        if mode == "updates"
        for value in chunk.values()
        if isinstance(value, dict) and isinstance(value.get("response"), dict)
    ]
    assert responses and responses[-1]["text"] == "流式答案"
