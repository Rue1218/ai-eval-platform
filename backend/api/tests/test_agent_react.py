"""M4 ReAct 循环单测（OR-2/OR-4/OR-5）；不触碰 WS/DB/真实模型。"""

import asyncio

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.harness.execution import build_default_registry
from app.harness.memory import SerializableRequest
from app.llm import ModelResponse

_REACT_DONE = (
    '{"protocol": "react", "version": "react.v1", "thought": "已完成检索并总结", '
    '"tool": null, "arguments": {}, "done": true}'
)
_REACT_READ = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要读取文件", '
    '"tool": "read", "arguments": {"path": "a.txt"}, "done": false}'
)


def _serializable(text: str = "帮我读取文件") -> SerializableRequest:
    """构造可序列化请求投影（含工具意图关键词，触发 react 路由）。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


class _ScriptGateway:
    """按脚本依次返回响应的网关桩（invoke 路径）。"""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[object] = []

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        text = self.script.pop(0) if self.script else _REACT_DONE
        return ModelResponse(text=text, latency_ms=1)


def _collect(agent: LangGraphAgent, request: SerializableRequest) -> list[tuple[str, dict]]:
    """消费 Agent astream 全部输出。"""

    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(request):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _pending_events(events: list[tuple[str, dict]]) -> list[dict]:
    """提取全部 pending_events。"""
    return [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]


def test_tool_intent_keyword_routes_to_react() -> None:
    """OR-1：工具意图关键词路由到 react，走 invoke 而非 stream。"""
    gateway = _ScriptGateway([_REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    assert len(gateway.calls) >= 1
    # 无自定义流帧（ReAct 非流式）
    assert all(mode != "custom" for mode, _ in events)


def test_react_tool_then_done_emits_event_sequence() -> None:
    """OR-2：工具调用 → tool_result → 再模型调用 → done 收尾。"""
    gateway = _ScriptGateway([_REACT_READ, _REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    # tool_call + tool_result（read 沙箱未配置 → ok=False 但 Agent 继续）
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    assert len(gateway.calls) == 2


def test_react_done_immediately() -> None:
    """OR-2：首轮即 done，无工具调用。"""
    gateway = _ScriptGateway([_REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds == ["assistant_message", "response.completed"]
    assert len(gateway.calls) == 1
    # done 收尾回显 thought（PR-3 回显语义）
    payloads = [
        event["payload"]
        for event in _pending_events(events)
        if event["kind"] == "assistant_message"
    ]
    assert "已完成检索并总结" in payloads[0]["text"]


_REACT_WRITE = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要写入文件", '
    '"tool": "write", "arguments": {"path": "b.txt", "content": "x"}, "done": false}'
)
_REACT_EDIT = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要编辑文件", '
    '"tool": "edit", "arguments": {"path": "b.txt", "old": "x", "new": "y"}, "done": false}'
)


def test_react_budget_exhausted_emits_error() -> None:
    """OR-5：model_calls 预算耗尽 → error 收尾，不进入死循环。"""
    # 交替工具避开重复抑制；默认预算 model_calls=4，第 5 次调用即超限
    script = [_REACT_READ, _REACT_WRITE, _REACT_EDIT, _REACT_READ, _REACT_WRITE]
    gateway = _ScriptGateway(script)
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 1
    codes = [event["payload"].get("code") for event in _pending_events(events)]
    assert "BUDGET_EXCEEDED" in codes
    # 无死循环：模型调用次数有界（预算 4 + 首次调用）
    assert len(gateway.calls) <= 5


def test_react_repeat_call_suppressed() -> None:
    """OR-4：同一工具连续调用未推进 → 抑制并 error 收尾。"""
    gateway = _ScriptGateway([_REACT_READ, _REACT_READ])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 1
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert any("连续调用" in message for message in messages)
    # 仅第 1 轮产出 tool_call（第 2 轮被抑制，未产出第二个）
    assert kinds.count("tool_call") == 1


def test_react_parse_failure_emits_error() -> None:
    """协议解析失败 → error 收尾，不裸抛。"""
    gateway = _ScriptGateway(["不是 JSON"])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds == ["error"]


def test_react_observations_injected_into_next_call() -> None:
    """OR-3：上一轮工具结果注入下一轮上下文（to_observation）。"""
    gateway = _ScriptGateway([_REACT_READ, _REACT_DONE])
    agent = LangGraphAgent(gateway, build_default_registry())
    _collect(agent, _serializable())
    second_system = gateway.calls[1].system
    assert "【工具结果】" in second_system
    assert "read" in second_system
