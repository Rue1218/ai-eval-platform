"""LangGraph 模型调用层单测；不访问真实上游，不验证 Agent/Harness 行为。"""

import asyncio

import pytest

import app.llm.gateway as gateway_module
from app.adapters import AdapterResult, AdapterStreamEvent, AdapterToolCall, StreamAborted
from app.errors import AppError, ErrorCode
from app.llm import ModelConfig, ModelGateway, ModelRequest


def _request() -> ModelRequest:
    """构造不含真实密钥的模型请求夹具。"""
    return ModelRequest.from_messages(
        ModelConfig(
            protocol="openai_chat",
            base_url="https://model.example.com",
            model="test-model",
            api_key="test-secret",
        ),
        [{"role": "user", "content": "你好"}],
        system="你是测试助手",
    )


def test_invoke_runs_through_graph() -> None:
    """非流式调用经过 LangGraph 图并返回统一响应。"""
    seen: list[ModelRequest] = []

    def fake_invoke(request: ModelRequest) -> AdapterResult:
        seen.append(request)
        return AdapterResult("你好，世界", {"total_tokens": 3}, {"ok": True}, 12)

    response = ModelGateway(invoke_transport=fake_invoke).invoke(_request())

    assert response.text == "你好，世界"
    assert response.usage["total_tokens"] == 3
    assert seen[0].config.model == "test-model"


def test_ainvoke_runs_through_graph() -> None:
    """异步入口与同步入口共享同一模型响应契约。"""
    gateway = ModelGateway(
        invoke_transport=lambda _request: AdapterResult("异步响应", {}, {}, 1)
    )

    response = asyncio.run(gateway.ainvoke(_request()))

    assert response.text == "异步响应"


def test_stream_projects_content_reasoning_and_completion() -> None:
    """流式节点把正文、推理和 completed 收尾事件分开投影。"""
    gateway = ModelGateway(
        stream_transport=lambda _request, _abort=None: iter(
            [("reasoning", "先判断"), ("content", "最终答案")]
        )
    )

    events = list(gateway.stream(_request()))

    assert [(event.kind, event.text) for event in events[:2]] == [
        ("reasoning", "先判断"),
        ("content", "最终答案"),
    ]
    assert events[-1].kind == "completed"
    assert events[-1].response is not None
    assert events[-1].response.text == "最终答案"


def test_stream_projects_complete_native_tool_call() -> None:
    """P2-B：适配器完成工具参数后，网关先投影调用再在收尾响应保留它。"""
    gateway = ModelGateway(
        stream_transport=lambda _request, _abort=None: iter(
            [
                AdapterStreamEvent(
                    kind="tool_call",
                    tool_call=AdapterToolCall(
                        call_id="call_read_1",
                        name="read",
                        arguments={"path": "a.txt"},
                    ),
                )
            ]
        )
    )

    events = list(gateway.stream(_request()))

    assert [event.kind for event in events] == ["tool_call", "completed"]
    assert events[0].tool_call is not None
    assert events[0].tool_call.arguments == {"path": "a.txt"}
    assert events[-1].response is not None
    assert events[-1].response.tool_calls == (events[0].tool_call,)


def test_default_stream_transport_sends_native_tool_schema(monkeypatch) -> None:
    """P2-B：流式入口必须和非流式入口一样向适配器透传工具定义。"""
    seen: dict = {}

    def fake_stream_protocol(**kwargs):
        seen.update(kwargs)
        return iter([("content", "ok")])

    monkeypatch.setattr(gateway_module, "stream_protocol", fake_stream_protocol)
    request = ModelRequest.from_messages(
        _request().config,
        [{"role": "user", "content": "读取文件"}],
        tools=[
            {
                "name": "read",
                "description": "读取文件",
                "parameters_schema": {"type": "object"},
            }
        ],
    )

    list(ModelGateway().stream(request))

    assert seen["tools"] == [
        {
            "name": "read",
            "description": "读取文件",
            "parameters_schema": {"type": "object"},
        }
    ]


def test_stream_filters_reasoning_when_disabled() -> None:
    """关闭思考摘要时，网关仍保留正文但不向上层投影 reasoning。"""
    request = ModelRequest.from_messages(
        ModelConfig(
            protocol="openai_chat",
            base_url="https://model.example.com",
            model="test-model",
            reasoning_enabled=False,
        ),
        [{"role": "user", "content": "你好"}],
    )
    gateway = ModelGateway(
        stream_transport=lambda _request, _abort=None: iter(
            [("reasoning", "隐藏摘要"), ("content", "答案")]
        )
    )

    events = list(gateway.stream(request))

    assert [(event.kind, event.text) for event in events] == [("content", "答案"), ("completed", "")]


def test_astream_projects_same_events() -> None:
    """异步流式入口保持与同步事件顺序一致。"""
    gateway = ModelGateway(
        stream_transport=lambda _request, _abort=None: iter([("content", "异步答案")])
    )

    async def collect() -> list:
        return [event async for event in gateway.astream(_request())]

    events = asyncio.run(collect())

    assert [event.kind for event in events] == ["content", "completed"]
    assert events[-1].response is not None
    assert events[-1].response.text == "异步答案"


def test_stream_abort_is_not_mapped_to_internal_error() -> None:
    """流式取消保持受控异常，交由 Agent 回合决定停止后的交付。"""
    def abort(_request: ModelRequest, _abort: object | None = None):
        raise StreamAborted()

    gateway = ModelGateway(stream_transport=abort)

    with pytest.raises(StreamAborted):
        list(gateway.stream(_request()))


def test_should_abort_injected_via_runnable_config() -> None:
    """O-12 迁移：should_abort 经 RunnableConfig.configurable 注入并生效。"""
    seen: list[object | None] = []

    def transport(_request: ModelRequest, should_abort: object | None = None):
        seen.append(should_abort)
        return iter([("content", "ok")])

    gateway = ModelGateway(stream_transport=transport)
    events = list(
        gateway.stream(
            _request(),
            config={"configurable": {"abort": {"should_abort": lambda: True}}},
        )
    )

    assert len(seen) == 1
    assert seen[0] is not None
    assert seen[0]() is True
    assert events[-1].kind == "completed"


def test_unexpected_transport_error_is_redacted() -> None:
    """transport 意外异常归一为 INTERNAL，不把原始异常文本回传。"""
    def fail(_request: ModelRequest) -> AdapterResult:
        raise RuntimeError("secret upstream traceback")

    with pytest.raises(AppError) as error:
        ModelGateway(invoke_transport=fail).invoke(_request())

    assert error.value.code == ErrorCode.INTERNAL
    assert error.value.message == "模型调用失败"
    assert "secret upstream" not in str(error.value)


def test_model_config_repr_does_not_expose_api_key() -> None:
    """配置调试表示不包含 API Key。"""
    config = _request().config

    assert "test-secret" not in repr(config)
