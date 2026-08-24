"""M4 ReAct 循环单测（OR-2/OR-4/OR-5）；不触碰 WS/DB/真实模型。"""

import asyncio
import tempfile

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
# 模型输出工具名偶带尾随换行/空白（如 "read\n"）：strip 归一化后才能命中豁免。
# 注意 JSON 内须为转义序列 \n（Python 源码中写作 \\n），解析后工具名才是真实换行结尾。
_REACT_READ_NL = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要读取文件", '
    '"tool": "read\\n", "arguments": {"path": "a.txt"}, "done": false}'
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
    # 交替工具避开重复抑制（无沙箱目录时工具 ok=False，守卫不触发）；
    # 默认预算 model_calls=12，第 13 次调用即超限
    script = [
        _REACT_READ, _REACT_WRITE, _REACT_EDIT, _REACT_READ,
        _REACT_WRITE, _REACT_EDIT, _REACT_READ, _REACT_WRITE,
        _REACT_EDIT, _REACT_READ, _REACT_WRITE, _REACT_EDIT,
        _REACT_READ,
    ]
    gateway = _ScriptGateway(script)
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 1
    codes = [event["payload"].get("code") for event in _pending_events(events)]
    assert "BUDGET_EXCEEDED" in codes
    # 无死循环：模型调用次数有界（预算 12 + 首次调用）
    assert len(gateway.calls) <= 13


def test_react_repeat_call_suppressed_after_correction() -> None:
    """OR-4：有副作用工具首次相同调用给纠正机会；纠正后仍重复相同调用才 error 收尾。

    read/web_fetch 为只读幂等工具，豁免 OR-4（见 test_react_read_repeat_allowed_no_guard）；
    本用例用 write（有副作用）验证守卫仍生效。
    回归：硬错误分支曾漏清 repeat_retry，导致 react_route 再次回环 react_agent，
    脚本耗尽回退 done 才掩盖了死循环；修复后硬错误直接收尾（仅 3 次模型调用）。
    """
    # 第三次相同调用（纠正回环后仍重复）才触发硬错误
    with tempfile.TemporaryDirectory() as tmp:
        gateway = _ScriptGateway([_REACT_WRITE, _REACT_WRITE, _REACT_WRITE])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 1
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert any("连续调用" in message for message in messages)
    # 首次相同调用被纠正（不执行），仅 1 轮产出 tool_call
    assert kinds.count("tool_call") == 1
    # 硬错误后不再回环调模型：模型调用次数恰好为脚本长度 3
    assert len(gateway.calls) == 3


def test_react_repeat_first_gives_correction_then_done_cleanly() -> None:
    """OR-4 回归：有副作用工具相同调用触发纠正后，模型 done 收尾不得再回环触发错误。"""
    with tempfile.TemporaryDirectory() as tmp:
        gateway = _ScriptGateway([_REACT_WRITE, _REACT_WRITE, _REACT_DONE])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    # 无 error、无多余工具执行，干净收尾
    assert kinds.count("error") == 0
    assert kinds.count("tool_call") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    # 纠正环节透出 thought（思考过程可见）
    assert kinds.count("thought") >= 1


def test_react_read_repeat_allowed_no_guard() -> None:
    """OR-4 豁免：read 为只读幂等工具，重复相同读取直接执行，不触发纠正/硬错误。

    用户场景回归：模型重读同一文件不再报"工具 read 连续调用未推进，已终止"。
    （上限内重复：READONLY_REPEAT_LIMIT=3，3 次相同 read 全部执行）
    """
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway([_REACT_READ, _REACT_READ, _REACT_READ, _REACT_DONE])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    # 三次相同 read 全部执行（不豁免会只有 1 次 tool_call）
    assert kinds.count("tool_call") == 3
    assert kinds.count("tool_result") == 3
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_react_read_repeat_capped_after_limit() -> None:
    """OR-4：read 相同参数超过 READONLY_REPEAT_LIMIT 后注入纠正（不再执行），
    模型改 done 收尾则干净完成，不报错。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway([_REACT_READ, _REACT_READ, _REACT_READ, _REACT_READ])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    # 前 3 次相同 read 执行，第 4 次被纠正拦截（不执行）；脚本耗尽回退 done 收尾
    assert kinds.count("tool_call") == 3
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    assert len(gateway.calls) == 5


def test_react_read_repeat_capped_graceful_end_after_correction() -> None:
    """OR-4：read 超限纠正后仍用相同参数调用 → 基于已读内容优雅收尾（assistant_message），
    不再抛硬错误——弱模型纠正无效时保证用户拿到内容而非报错。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway(
            [_REACT_READ, _REACT_READ, _REACT_READ, _REACT_READ, _REACT_READ]
        )
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    # 前 3 次执行，第 4 次纠正，第 5 次仍相同 → 自动收尾；共 5 次模型调用，无死循环
    assert kinds.count("tool_call") == 3
    assert len(gateway.calls) == 5
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    # 收尾消息回显已读内容（模型拿不到的内容由系统补上）
    final = [
        e["payload"].get("text", "") for e in _pending_events(events) if e["kind"] == "assistant_message"
    ]
    assert any("hello" in message for message in final)


def test_react_read_toolname_with_newline_exempt_from_guard() -> None:
    """OR-4 豁免 + strip 兜底：模型输出工具名带尾随换行（"read\n"）时，
    归一化后命中 READONLY_TOOLS，重复相同读取仍直接执行，不报
    「工具 read 连续调用未推进，已终止」。
    """
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway(
            [_REACT_READ_NL, _REACT_READ_NL, _REACT_READ_NL, _REACT_DONE]
        )
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    assert not any("未注册" in message for message in messages)
    # 三次相同 read 全部执行（strip 前 "read\n" 不命中豁免会被守卫拦截）
    assert kinds.count("tool_call") == 3
    assert kinds.count("tool_result") == 3
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_react_retry_after_failed_call_allowed() -> None:
    """OR-4 回归：先前相同调用「失败」时，模型重试是合法行为，不触发重复守卫。

    edit 目标不存在 → NOT_FOUND(ok=False)；模型重试同一 edit 应正常执行而非被拦。
    """
    with tempfile.TemporaryDirectory() as tmp:
        gateway = _ScriptGateway([_REACT_EDIT, _REACT_EDIT, _REACT_DONE])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    # 两次 edit 都执行了（失败后重试不被判为"未推进"）
    assert kinds.count("tool_call") == 2
    assert kinds.count("tool_result") == 2
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_react_parse_failure_recovers_with_correction() -> None:
    """协议解析失败 → 注入纠正观察回环一次，模型改输出协议 JSON 后正常收尾（不报错）。

    用户场景回归：模型输出非有效 JSON（"不是 JSON"）不再直接 error 收尾。
    """
    gateway = _ScriptGateway(["不是 JSON", _REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    # 模型调用 2 次：首次输出坏 JSON 被纠正，第二次 done 收尾
    assert len(gateway.calls) == 2
    # 纠正观察进入第二次调用的系统上下文（模型能看到自己上轮的坏输出）
    assert "不是 JSON" in gateway.calls[1].system


def test_react_parse_failure_exhausts_retries_then_error() -> None:
    """协议解析失败达到 MAX_PARSE_RETRIES 上限 → 硬错误收尾，不裸抛、不死循环。"""
    gateway = _ScriptGateway(["不是 JSON", "还是不对", "依旧不是 JSON", _REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 1
    codes = [event["payload"].get("code") for event in _pending_events(events)]
    assert "VALIDATION" in codes
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert any("不是有效 JSON" in message for message in messages)
    # 上限 2 次纠正 + 首次坏输出 = 3 次模型调用后硬错误，无死循环
    assert len(gateway.calls) == 3


def test_react_observations_injected_into_next_call() -> None:
    """OR-3：上一轮工具结果注入下一轮上下文（to_observation）。"""
    gateway = _ScriptGateway([_REACT_READ, _REACT_DONE])
    agent = LangGraphAgent(gateway, build_default_registry())
    _collect(agent, _serializable())
    second_system = gateway.calls[1].system
    assert "【工具结果】" in second_system
    assert "read" in second_system
