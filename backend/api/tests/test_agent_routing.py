"""M4 编排层路由单测（阶段 1：O-A1~O-A4）；不触碰 WS/DB/真实模型。"""

import asyncio

import pytest

from app.adapters import StreamAborted
from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.harness.memory import GraphState, SerializableRequest
from app.llm import ModelRequest, ModelResponse, ModelStreamEvent


def _serializable(text: str = "你好") -> SerializableRequest:
    """构造可序列化请求投影（不含回调/api_key）。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


class _FakeGateway:
    """记录调用并返回固定流事件的网关桩。"""

    def __init__(self) -> None:
        self.stream_calls: list[ModelRequest] = []

    def stream(self, request: ModelRequest, config: dict | None = None):
        """记录请求并返回推理/正文事件（可注入取消回调）。"""
        self.stream_calls.append(request)
        abort = None
        if config:
            abort = config.get("configurable", {}).get("abort", {}).get("should_abort")
        if abort is not None and abort():
            raise StreamAborted()
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


def _collect(
    agent: LangGraphAgent,
    request: SerializableRequest,
    config: dict | None = None,
) -> list[tuple[str, dict]]:
    """消费 Agent astream 全部输出。"""

    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(request, config=config):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _event_kinds(events: list[tuple[str, dict]]) -> list[str]:
    """从 updates 增量中提取全部 pending_events kind。"""
    return [
        event["kind"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]


def _error_payloads(events: list[tuple[str, dict]]) -> list[dict]:
    """从 updates 增量中提取 error 事件 payload。"""
    return [
        event["payload"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
        if event["kind"] == "error"
    ]


def test_routing_slash_goes_direct_no_model_call() -> None:
    """O-A1：斜杠 text 进 Direct 分支，不调模型。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("/help"))
    assert gateway.stream_calls == []
    assert _event_kinds(events) == ["assistant_message"]


def test_routing_plain_text_goes_chat() -> None:
    """O-A1：非斜杠 text 进 Chat 分支，调模型并投影事件。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    assert len(gateway.stream_calls) == 1
    custom = [chunk for mode, chunk in events if mode == "custom"]
    assert [(c["kind"], c["text"]) for c in custom] == [
        ("reasoning", "先判断"),
        ("content", "流式答案"),
    ]
    assert _event_kinds(events) == ["assistant_message", "response.completed"]


def test_unknown_slash_returns_validation() -> None:
    """O-A1：未知斜杠返回 VALIDATION error 事件，不调模型。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("/nope"))
    assert gateway.stream_calls == []
    assert _error_payloads(events) == [
        {"code": "VALIDATION", "message": "未知斜杠命令：/nope"}
    ]


def test_unimplemented_slash_returns_validation() -> None:
    """阶段 1：/compact /cancel /stress 未启用返回 VALIDATION。"""
    for command in ("/compact", "/cancel", "/stress"):
        gateway = _FakeGateway()
        events = _collect(LangGraphAgent(gateway), _serializable(command))
        assert gateway.stream_calls == []
        assert _error_payloads(events) == [
            {"code": "VALIDATION", "message": f"{command} 能力未启用，将在后续版本开放"}
        ]


def test_graph_state_has_no_should_abort_field() -> None:
    """O-A2：should_abort 不出现在 GraphState 字段中（反射断言）。"""
    annotations = GraphState.__annotations__
    assert "should_abort" not in annotations
    # 回调不得以任何形式入 State
    assert "request" in annotations  # 投影（SerializableRequest，无回调）


def test_should_abort_via_runnable_config_triggers_stream_aborted() -> None:
    """O-A3：取消回调经 RunnableConfig.configurable 注入，取消触发 StreamAborted。"""
    gateway = _FakeGateway()
    agent = LangGraphAgent(gateway)
    config = {"configurable": {"abort": {"should_abort": lambda: True}}}
    with pytest.raises(StreamAborted):
        _collect(agent, _serializable("你好"), config=config)


def test_should_abort_not_triggered_when_absent() -> None:
    """O-A3：未注入取消回调时正常完成（向后兼容）。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    assert _event_kinds(events) == ["assistant_message", "response.completed"]


def test_node_events_emitted_via_pending_events() -> None:
    """O-A4：节点产出 NodeEvent 写入 pending_events，经 updates 可见。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    assert all(event["event_version"] == "event.v1" for event in pending)
    # pending_events 是纯数据（可序列化，无回调/连接）
    import json

    json.dumps(pending)
