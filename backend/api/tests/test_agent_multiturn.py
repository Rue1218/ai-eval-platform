"""多轮对话回归测试（工具调用链路的跨回合行为）。

覆盖此前修复的回归点：
- OR-4 守卫：不同命令的连续工具调用不被误杀（原只比较工具名）
- OR-4 纠正机制：首次相同调用给纠正机会，done 收尾不再回环触发错误
- gateway.invoke/ainvoke 接受 config 参数（原 react 路径 TypeError）
- skill_hints 接入工具列表（系统提示词不再显示"可见技能：（无）"）
- 每轮 ReAct thought 透出为 thought 事件

不触碰 WS/DB/真实模型；用脚本化网关桩驱动完整多轮图。
"""

import asyncio
import tempfile

from app.adapters import AdapterResult
from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.harness.execution import build_default_registry
from app.harness.memory import SerializableRequest
from app.llm import ModelGateway, ModelRequest

_REACT_DONE = (
    '{"protocol": "react", "version": "react.v1", "thought": "任务已完成并总结", '
    '"tool": null, "arguments": {}, "done": true}'
)
_REACT_LS = (
    '{"protocol": "react", "version": "react.v1", "thought": "先列出工作区文件", '
    '"tool": "bash", "arguments": {"command": "ls -la"}, "done": false}'
)
_REACT_CAT = (
    '{"protocol": "react", "version": "react.v1", "thought": "再读取文件内容", '
    '"tool": "bash", "arguments": {"command": "cat probe.txt"}, "done": false}'
)
# 有副作用工具（write）用于验证 OR-4 重复守卫：无需 bwrap，测试环境确定性成功。
_REACT_WRITE = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要写入文件", '
    '"tool": "write", "arguments": {"path": "b.txt", "content": "x"}, "done": false}'
)


def _serializable(text: str = "请读取工作区文件列表") -> SerializableRequest:
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
        return _model_response(text)


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


def _run(script: list[str], text: str = "请读取工作区文件列表") -> list[dict]:
    """驱动一次完整多轮图执行，返回全部事件。

    注入临时沙箱目录：write 等受控目录工具确定性成功（不依赖 bwrap）。
    """
    gateway = _ScriptGateway(script)
    with tempfile.TemporaryDirectory() as tmp:
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(text),
        )
    return gateway, _pending_events(events)


# —— 多轮工具调用回归 ——


def test_single_tool_then_clean_done_no_stale_loop() -> None:
    """回归：一次工具调用后 done 干净收尾，不得有多余回环或错误。"""
    gateway, events = _run([_REACT_LS, _REACT_DONE])
    kinds = [event["kind"] for event in events]
    assert kinds.count("error") == 0
    assert kinds.count("tool_call") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    assert len(gateway.calls) == 2


def test_consecutive_different_bash_calls_allowed() -> None:
    """回归：连续两个不同命令的 bash 调用不被 OR-4 误杀。"""
    gateway, events = _run([_REACT_LS, _REACT_CAT, _REACT_DONE])
    kinds = [event["kind"] for event in events]
    assert kinds.count("error") == 0
    assert kinds.count("tool_call") == 2
    tool_args = [
        event["payload"]["arguments"] for event in events if event["kind"] == "tool_call"
    ]
    assert tool_args == [{"command": "ls -la"}, {"command": "cat probe.txt"}]
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_identical_repeat_corrected_then_different_command() -> None:
    """回归：相同调用触发纠正（不执行）→ 模型换新命令执行 → 干净收尾。"""
    gateway, events = _run([_REACT_WRITE, _REACT_WRITE, _REACT_CAT, _REACT_DONE])
    kinds = [event["kind"] for event in events]
    assert kinds.count("error") == 0
    # 首次相同调用被纠正不执行；换命令后真正执行一次
    assert kinds.count("tool_call") == 2
    assert kinds.count("thought") >= 2
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_identical_repeat_corrected_then_done_clean_end() -> None:
    """回归（用户场景）：相同调用纠正后模型直接 done 收尾，不得再回环报错。"""
    gateway, events = _run([_REACT_WRITE, _REACT_WRITE, _REACT_DONE])
    kinds = [event["kind"] for event in events]
    assert kinds.count("error") == 0
    assert kinds.count("tool_call") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_identical_repeat_twice_hard_error() -> None:
    """兜底：纠正后仍重复相同调用才硬错误终止。"""
    gateway, events = _run([_REACT_WRITE, _REACT_WRITE, _REACT_WRITE])
    kinds = [event["kind"] for event in events]
    assert kinds.count("error") == 1
    messages = [event["payload"].get("message", "") for event in events]
    assert any("连续调用" in message for message in messages)
    assert kinds.count("tool_call") == 1


def test_tool_path_emits_thought_events() -> None:
    """回归：工具调用每轮 thought 透出，思考过程可见。"""
    gateway, events = _run([_REACT_LS, _REACT_DONE])
    thoughts = [event for event in events if event["kind"] == "thought"]
    assert len(thoughts) >= 1
    # 工具调用轮次的 thought 携带思考文本
    assert any(event["payload"].get("text") for event in thoughts)


def test_react_system_prompt_skill_hints_list_tools() -> None:
    """回归：skill_hints 接入工具列表，系统提示词不再显示"（无）"。"""
    gateway = _ScriptGateway([_REACT_DONE])
    agent = LangGraphAgent(gateway, build_default_registry())
    _collect(agent, _serializable())
    system = gateway.calls[0].system
    assert "（无）" not in system
    assert "bash" in system
    assert "read" in system


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
