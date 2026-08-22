"""LangGraph Agent 图单测；不触碰 WebSocket、数据库或真实模型服务。"""

import asyncio

from app.agent import LangGraphAgent
from app.llm import ModelConfig, ModelRequest, ModelResponse, ModelStreamEvent


def _request() -> ModelRequest:
    """构造单轮 Agent 测试请求。"""
    return ModelRequest.from_messages(
        ModelConfig(
            protocol="openai_chat",
            base_url="https://model.example.com",
            model="test-model",
        ),
        [{"role": "user", "content": "你好"}],
    )


class _FakeGateway:
    """仅实现 Agent 图依赖的最小网关接口。"""

    def invoke(self, _request: ModelRequest) -> ModelResponse:
        """返回固定的非流式响应。"""
        return ModelResponse(text="非流式答案", latency_ms=1)

    def stream(self, _request: ModelRequest):
        """返回推理、正文和收尾事件，模拟模型网关输出。"""
        response = ModelResponse(text="流式答案", latency_ms=2)
        return iter(
            [
                ModelStreamEvent(kind="reasoning", text="先判断"),
                ModelStreamEvent(kind="content", text="流式答案"),
                ModelStreamEvent(kind="completed", response=response),
            ]
        )


def test_agent_invoke_uses_langgraph_node() -> None:
    """Agent 非流式入口通过 LangGraph 节点调用注入网关。"""
    response = LangGraphAgent(_FakeGateway()).invoke(_request())

    assert response.text == "非流式答案"


def test_agent_astream_projects_gateway_events() -> None:
    """Agent 流式入口保留推理、正文和 completed 事件顺序。"""
    async def collect() -> list[ModelStreamEvent]:
        return [event async for event in LangGraphAgent(_FakeGateway()).astream(_request())]

    events = asyncio.run(collect())

    assert [(event.kind, event.text) for event in events[:2]] == [
        ("reasoning", "先判断"),
        ("content", "流式答案"),
    ]
    assert events[-1].kind == "completed"
    assert events[-1].response is not None
    assert events[-1].response.text == "流式答案"
