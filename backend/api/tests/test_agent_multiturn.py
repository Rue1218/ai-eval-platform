"""多轮对话回归测试（纯对话骨架版）。

覆盖此前修复的回归点（骨架化后保留与纯对话相关的部分）：
- gateway.invoke/ainvoke 接受 config 参数（原 react 路径 TypeError）
- assemble 常驻 Skill Hint（系统提示词不再显示"可见技能：（无）"）
- 连续多轮纯对话各自产生完整的 assistant_message + response.completed

不触碰 WS/DB/真实模型；用脚本化网关桩驱动完整图。
"""

import asyncio

from app.adapters import AdapterResult
from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.harness.memory import SerializableRequest
from app.llm import ModelGateway, ModelRequest


def _serializable(text: str = "你好") -> SerializableRequest:
    """构造可序列化请求投影（纯对话入口）。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


class _ScriptGateway:
    """按脚本依次返回响应的网关桩（纯对话 stream 路径）。"""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[object] = []

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        text = self.script.pop(0) if self.script else "好的。"
        return _model_response(text)

    def stream(self, request: object, config: dict | None = None):
        """模拟纯对话流式输出：正文增量 + completed 收尾。"""
        from app.llm import ModelStreamEvent

        self.calls.append(request)
        text = self.script.pop(0) if self.script else "好的。"
        yield ModelStreamEvent(kind="content", text=text)
        yield ModelStreamEvent(kind="completed", response=_model_response(text))


def _model_response(text: str):
    from app.llm import ModelResponse

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


def _run(script: list[str], text: str = "你好") -> list[dict]:
    """驱动一次完整图执行，返回全部事件。"""
    gateway = _ScriptGateway(script)
    events = _collect(LangGraphAgent(gateway), _serializable(text))
    return gateway, _pending_events(events)


# —— 纯对话多轮回归 ——


def test_single_turn_clean_completion() -> None:
    """回归：单轮对话干净收尾，事件序列恒为 assistant_message + response.completed。"""
    gateway, events = _run(["你好！"])
    kinds = [event["kind"] for event in events]
    assert kinds.count("error") == 0
    assert kinds == ["assistant_message", "response.completed"]
    assert len(gateway.calls) == 1
    # 纯对话不注入工具定义
    assert getattr(gateway.calls[0], "tools", ()) == ()


def test_consecutive_turns_each_complete() -> None:
    """回归：连续多轮对话各自产生完整的回复与收尾，不串回合。"""
    for text in ("第一轮问题", "第二轮问题", "第三轮问题"):
        gateway, events = _run([f"回答：{text}"], text)
        kinds = [event["kind"] for event in events]
        assert kinds.count("error") == 0
        assert kinds == ["assistant_message", "response.completed"]


def test_no_internal_thought_events() -> None:
    """骨架化：纯对话不再产出 thought / tool_call 等过程事件。"""
    gateway, events = _run(["回答"])
    assert not any(event["kind"] in ("thought", "tool_call", "plan") for event in events)


def test_system_prompt_skill_hints_present() -> None:
    """回归：assemble 注入常驻 Skill Hint，不再显示"（无）"。"""
    gateway = _ScriptGateway(["好的。"])
    agent = LangGraphAgent(gateway)
    _collect(agent, _serializable())
    system = gateway.calls[0].system
    assert "（无）" not in system
    assert "基准评测" in system


# —— gateway config 参数回归 ——


def _build_request() -> ModelRequest:
    from app.llm import ModelConfig

    config = ModelConfig(
        protocol="openai_chat",
        base_url="https://model.example.com",
        model="test-model",
    )
    return ModelRequest(
        config=config,
        messages=[{"role": "user", "content": "hi"}],
        system="test",
    )


def test_gateway_invoke_accepts_config_param() -> None:
    """回归：ModelGateway.invoke 接受 config 参数（原 react 路径 TypeError）。"""

    def transport(request: ModelRequest) -> AdapterResult:
        return AdapterResult(text="ok", usage={}, raw={}, latency_ms=1)

    gateway = ModelGateway(invoke_transport=transport)
    response = gateway.invoke(_build_request(), config={})
    assert response.text == "ok"


def test_gateway_ainvoke_accepts_config_param() -> None:
    """回归：ModelGateway.ainvoke 接受 config 参数。"""

    def transport(request: ModelRequest) -> AdapterResult:
        return AdapterResult(text="ok", usage={}, raw={}, latency_ms=1)

    gateway = ModelGateway(invoke_transport=transport)
    response = asyncio.run(gateway.ainvoke(_build_request(), config={}))
    assert response.text == "ok"
