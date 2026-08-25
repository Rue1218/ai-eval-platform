"""M4 ReAct 循环单测（OR-2/OR-4/OR-5）；不触碰 WS/DB/真实模型。"""

import asyncio
import tempfile

import pytest

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.harness.execution import build_default_registry
from app.harness.memory import InMemoryCheckpointer, SerializableRequest
from app.llm import ModelResponse, ModelStreamEvent, NativeToolCall

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


def _serializable(
    text: str = "帮我读取文件",
    *,
    tool_call_mode: str = "native",
    system: str | None = None,
) -> SerializableRequest:
    """构造可序列化请求投影（含工具意图关键词，触发 react 路由）。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
            "tool_call_mode": tool_call_mode,
        },
        messages=({"role": "user", "content": text},),
        system=system,
    )


class _ScriptGateway:
    """按脚本依次返回响应的网关桩（invoke 路径）。"""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[object] = []

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        # 无工具请求是工具链收敛后的自然语言回答；脚本未显式指定时提供
        # 非协议正文，避免夹具把 ReAct JSON 误当作最终回答。
        if self.script:
            text = self.script.pop(0)
        elif getattr(request, "tools", ()) == ():
            text = "工具结果已整理。"
        else:
            text = _REACT_DONE
        return ModelResponse(text=text, latency_ms=1)


class _StreamingAfterToolGateway(_ScriptGateway):
    """工具链收敛后返回自然语言流事件的网关桩。"""

    def __init__(self, script: list[str]) -> None:
        super().__init__(script)
        self.stream_calls: list[object] = []

    def stream(self, request: object, config: dict | None = None):
        """模拟最终回答的推理/正文增量与 completed 收尾。"""
        self.stream_calls.append(request)
        return iter(
            [
                ModelStreamEvent(kind="content", text="工具结果"),
                ModelStreamEvent(kind="content", text="已整理"),
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text="工具结果已整理", latency_ms=2),
                ),
            ]
        )


class _NativeToolCallGateway:
    """模拟支持原生 ToolCall 的模型，验证回传结果后的流式收敛。"""

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.configs: list[dict | None] = []
        self.stream_calls: list[object] = []
        self.stream_configs: list[dict | None] = []

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        self.configs.append(config)
        if len(self.calls) == 1:
            return ModelResponse(
                text="",
                latency_ms=1,
                tool_calls=(
                    NativeToolCall("call_read_a", "read", {"path": "a.txt"}),
                    NativeToolCall("call_read_b", "read", {"path": "b.txt"}),
                ),
            )
        return ModelResponse(text="两个文件已读取，开始汇总。", latency_ms=1)

    def stream(self, request: object, config: dict | None = None):
        self.stream_calls.append(request)
        self.stream_configs.append(config)
        return iter(
            [
                ModelStreamEvent(kind="content", text="两个文件的共同结论是："),
                ModelStreamEvent(kind="content", text="都可用于后续评测。"),
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text="两个文件的共同结论是：都可用于后续评测。", latency_ms=2),
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
    # read、ReAct 收敛判断、无工具最终回答三次模型调用。
    assert len(gateway.calls) == 3
    assert gateway.calls[-1].tools == ()


def test_react_tool_then_done_streams_final_answer() -> None:
    """工具返回后，最终自然语言回答应产生 custom 正文增量。"""
    gateway = _StreamingAfterToolGateway([_REACT_READ, _REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())

    custom = [chunk for mode, chunk in events if mode == "custom"]
    assert [(chunk["kind"], chunk["text"]) for chunk in custom] == [
        ("content", "工具结果"),
        ("content", "已整理"),
    ]
    final = [
        event["payload"]["text"]
        for event in _pending_events(events)
        if event["kind"] == "assistant_message"
    ]
    assert final == ["工具结果已整理"]
    assert len(gateway.calls) == 2
    assert len(gateway.stream_calls) == 1
    assert gateway.stream_calls[0].tools == ()


def test_native_tool_calls_keep_call_id_and_stream_final_answer() -> None:
    """P2-B：同轮原生多 ToolCall 回传后，以第二次模型调用流式收敛。"""
    gateway = _NativeToolCallGateway()
    checkpointer = InMemoryCheckpointer()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("A 文件内容")
        with open(f"{tmp}/b.txt", "w", encoding="utf-8") as handle:
            handle.write("B 文件内容")
        agent = LangGraphAgent(
            gateway,
            build_default_registry(),
            sandbox_dir=tmp,
            checkpointer=checkpointer,
        )
        events = _collect(
            agent,
            _serializable(),
            {
                "configurable": {
                    "thread_id": "native-tool-result-test",
                    "credentials": {"api_key": "test-secret"},
                }
            },
        )

    pending = _pending_events(events)
    calls = [event["payload"] for event in pending if event["kind"] == "tool_call"]
    results = [event["payload"] for event in pending if event["kind"] == "tool_result"]
    assert [payload["call_id"] for payload in calls] == ["call_read_a", "call_read_b"]
    assert [payload["call_id"] for payload in results] == ["call_read_a", "call_read_b"]
    assert [payload["name"] for payload in calls] == ["read", "read"]
    assert all(payload["ok"] is True for payload in results)
    # 首轮仅调用一次非流式模型；携带 ToolResult 的第二轮改走原生工具流。
    assert len(gateway.calls) == 1
    # 第二轮模型可见标准 assistant ToolCall + 两条对应 role=tool 结果，非 Observation 拼接。
    native_messages = gateway.stream_calls[0].messages[-3:]
    assert native_messages[0]["role"] == "assistant"
    assert [call["call_id"] for call in native_messages[0]["tool_calls"]] == ["call_read_a", "call_read_b"]
    assert [message["tool_call_id"] for message in native_messages[1:]] == ["call_read_a", "call_read_b"]
    assert [message["content"] for message in native_messages[1:]] == ["A 文件内容", "B 文件内容"]
    # 完整文件正文和凭据均不得沿 RunnableConfig 传入模型网关。
    assert gateway.configs == [{"configurable": {}}]
    assert len(gateway.stream_calls) == 1
    assert gateway.stream_configs == [{"configurable": {}}]
    # 原文必须只存在于当次模型输入，不能随图状态写入检查点。
    checkpoints = [item.checkpoint for item in checkpointer.list()]
    saved_native_messages = [
        message
        for checkpoint in checkpoints
        for message in checkpoint["channel_values"].get("native_messages", [])
    ]
    saved_tool_messages = [
        message
        for message in saved_native_messages
        if message.get("role") == "tool"
    ]
    assert saved_tool_messages
    assert all(message.get("content") == "" for message in saved_tool_messages)
    assert gateway.stream_calls[0].tools
    custom = [chunk for mode, chunk in events if mode == "custom"]
    assert [(chunk["kind"], chunk["text"]) for chunk in custom] == [
        ("content", "两个文件的共同结论是："),
        ("content", "都可用于后续评测。"),
    ]


def test_native_tool_calls_emit_interim_narration() -> None:
    """P1：native 同轮正文 + ToolCall 先发 interim 阶段叙述，不是 Observation。"""

    class _NarratingGateway(_NativeToolCallGateway):
        def invoke(self, request: object, config: dict | None = None):
            response = super().invoke(request, config)
            if response.tool_calls:
                return ModelResponse(
                    text="先读取两个附件再汇总",
                    latency_ms=1,
                    tool_calls=response.tool_calls,
                )
            return response

    gateway = _NarratingGateway()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("A 文件内容")
        with open(f"{tmp}/b.txt", "w", encoding="utf-8") as handle:
            handle.write("B 文件内容")
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    messages = [
        event
        for event in _pending_events(events)
        if event["kind"] == "assistant_message"
    ]
    assert messages[0]["payload"]["interim"] is True
    assert messages[0]["payload"]["text"] == "先读取两个附件再汇总"
    assert "A 文件内容" not in messages[0]["payload"]["text"]


@pytest.mark.parametrize("call_ids", [("", "second"), ("duplicated", "duplicated")])
def test_native_tool_calls_reject_empty_or_duplicate_call_id(call_ids: tuple[str, str]) -> None:
    """上游空/重复 call_id 必须在 ReAct 入队前归一为 UPSTREAM。"""

    class _InvalidCallIdGateway:
        def invoke(self, _request: object, config: dict | None = None):
            return ModelResponse(
                text="",
                latency_ms=1,
                tool_calls=(
                    NativeToolCall(call_ids[0], "read", {"path": "a.txt"}),
                    NativeToolCall(call_ids[1], "read", {"path": "b.txt"}),
                ),
            )

    events = _collect(
        LangGraphAgent(_InvalidCallIdGateway(), build_default_registry()), _serializable()
    )
    pending = _pending_events(events)
    assert [event["kind"] for event in pending] == ["error"]
    assert pending[0]["payload"]["code"] == "UPSTREAM"


def test_legacy_profile_does_not_send_native_tools() -> None:
    """不支持 tools 的协议档走严格 JSON ReAct，避免上游请求先于回退失败。"""
    gateway = _ScriptGateway([_REACT_DONE])
    _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable(tool_call_mode="legacy"),
    )
    assert gateway.calls[0].tools == ()
    assert "每轮输出严格 JSON" in gateway.calls[0].system


def test_react_preserves_configured_system_prompt() -> None:
    """ReAct 必须保留 ws.py 注入的系统提示词，再追加工具约束。"""
    gateway = _ScriptGateway([_REACT_DONE])
    _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable(system="【自定义平台规则】读取后必须先总结。"),
    )
    assert "【自定义平台规则】读取后必须先总结。" in gateway.calls[0].system
    assert "【本轮可用平台工具】" in gateway.calls[0].system


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
    # 前 3 次相同 read 执行，第 4 次被纠正拦截；随后控制模型 done，再进行
    # 一次无工具最终回答。
    assert kinds.count("tool_call") == 3
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    assert len(gateway.calls) == 6
    assert gateway.calls[-1].tools == ()


def test_react_read_repeat_capped_uses_model_summary_after_correction() -> None:
    """重复 read 被强制收敛时，最终消息必须来自模型而不是工具原文。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway(
            [
                _REACT_READ,
                _REACT_READ,
                _REACT_READ,
                _REACT_READ,
                _REACT_READ,
                "文件内容已用于完成分析；建议继续按需求核对。",
            ]
        )
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    # 前 3 次执行，第 4 次纠正，第 5 次仍相同后进入无工具最终回答；共 6 次模型调用。
    assert kinds.count("tool_call") == 3
    assert len(gateway.calls) == 6
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    # 最终正文来自无工具模型回合，不得直接回显 read 的原文 "hello"。
    final = [
        e["payload"].get("text", "") for e in _pending_events(events) if e["kind"] == "assistant_message"
    ]
    assert final == ["文件内容已用于完成分析；建议继续按需求核对。"]
    assert all("hello" not in message for message in final)
    assert gateway.calls[-1].tools == ()


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


def test_react_stage_input_uses_observe_think_act() -> None:
    """P0：ReAct / native 阶段输入写明先观察再思考再行动。"""
    from app.agent.react import NATIVE_TOOL_STAGE_INPUT, REACT_STAGE_INPUT

    assert "Observe → Think → Act" in REACT_STAGE_INPUT
    assert "【工具结果】" in REACT_STAGE_INPUT
    assert "Observe → Think → Act" in NATIVE_TOOL_STAGE_INPUT
    assert "不要把工具原文粘贴成助手正文" in NATIVE_TOOL_STAGE_INPUT
