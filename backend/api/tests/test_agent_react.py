"""M4 ReAct 循环单测（OR-2/OR-4/OR-5）；不触碰 WS/DB/真实模型。"""

import asyncio
import os
import tempfile

import pytest

import app.agent.react as react_module
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
# 反幻觉：模型未调用任何工具即输出 done=true，thought 声称已成功更新文件。
_HALLUCINATED_DONE = (
    '{"protocol": "react", "version": "react.v1", '
    '"thought": "已将 g.txt 的内容更新为 beta", "tool": null, "arguments": {}, "done": true}'
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
        """带工具的 native 回合降级为一次 completed；无工具才流式最终回答。"""
        if getattr(request, "tools", ()):
            response = self.invoke(request, config)
            return iter([ModelStreamEvent(kind="completed", response=response)])
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


def test_stream_final_answer_can_hold_content_until_reflect_passes(monkeypatch) -> None:
    """chat 规划待 Reflect 审核时，最终正文增量不得提前发送给浏览器。"""
    emitted: list[dict] = []
    monkeypatch.setattr(react_module, "get_stream_writer", lambda: emitted.append)

    class _Gateway:
        """构造最小流式最终回答网关。"""

        def stream(self, request: object, config: dict | None = None):
            return iter(
                [
                    ModelStreamEvent(kind="content", text="暂存正文"),
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(text="暂存正文", latency_ms=1),
                    ),
                ]
            )

    response = react_module._stream_final_answer(_Gateway(), object(), {}, emit_content=False)
    assert response is not None
    assert response.text == "暂存正文"
    assert not emitted


class _NativeToolCallGateway:
    """模拟支持原生 ToolCall 的模型：首轮流式正文 + 完整调用，结果后再流式收敛。"""

    FIRST_TEXT = "先读取两个附件再汇总"
    FINAL_PARTS = ("两个文件的共同结论是：", "都可用于后续评测。")

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.configs: list[dict | None] = []
        self.stream_calls: list[object] = []
        self.stream_configs: list[dict | None] = []

    @staticmethod
    def _first_tool_calls() -> tuple[NativeToolCall, NativeToolCall]:
        return (
            NativeToolCall("call_read_a", "read", {"path": "a.txt"}),
            NativeToolCall("call_read_b", "read", {"path": "b.txt"}),
        )

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        self.configs.append(config)
        if len(self.calls) == 1:
            return ModelResponse(
                text=self.FIRST_TEXT,
                latency_ms=1,
                tool_calls=self._first_tool_calls(),
            )
        return ModelResponse(text="两个文件已读取，开始汇总。", latency_ms=1)

    def stream(self, request: object, config: dict | None = None):
        self.stream_calls.append(request)
        self.stream_configs.append(config)
        if len(self.stream_calls) == 1:
            calls = self._first_tool_calls()
            return iter(
                [
                    ModelStreamEvent(kind="content", text=self.FIRST_TEXT),
                    *(
                        ModelStreamEvent(kind="tool_call", tool_call=call)
                        for call in calls
                    ),
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(
                            text=self.FIRST_TEXT,
                            latency_ms=1,
                            tool_calls=calls,
                        ),
                    ),
                ]
            )
        final_text = "".join(self.FINAL_PARTS)
        return iter(
            [
                ModelStreamEvent(kind="content", text=self.FINAL_PARTS[0]),
                ModelStreamEvent(kind="content", text=self.FINAL_PARTS[1]),
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text=final_text, latency_ms=2),
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

    custom = [
        chunk
        for mode, chunk in events
        if mode == "custom" and chunk.get("kind") == "content"
    ]
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


def test_requested_tool_guard_returns_correction() -> None:
    """反幻觉：用户明确要求调用工具且无工具结果时，守卫返回强制调用纠正。"""
    from app.agent.react import GUARD_TOOL, _requested_tool_correction

    state: dict = {
        "request": {
            "messages": ({"role": "user", "content": "用 write 工具把 g.txt 内容改为 beta"},)
        },
        "observations": [],
    }
    guard = _requested_tool_correction(state)
    assert guard is not None
    assert guard.tool == GUARD_TOOL
    assert "write" in guard.text
    assert "尚未调用任何工具" in guard.text


def test_requested_tool_guard_passes_when_tool_result_exists() -> None:
    """已有真实工具结果时守卫放行（不误伤正常工具链收尾）。"""
    from app.agent.react import _requested_tool_correction
    from app.harness.contracts import Observation

    state: dict = {
        "request": {
            "messages": ({"role": "user", "content": "用 read 工具读取 a.txt"},)
        },
        "observations": [
            Observation(tool="read", text="a.txt 内容", ok=True),
        ],
    }
    assert _requested_tool_correction(state) is None


def test_requested_tool_guard_ignores_plain_mention() -> None:
    """仅提及工具名（无动作词）不触发守卫，避免"解释什么是 bash"误伤。"""
    from app.agent.react import _requested_tool_correction

    state: dict = {
        "request": {
            "messages": ({"role": "user", "content": "解释一下什么是 bash"},)
        },
        "observations": [],
    }
    assert _requested_tool_correction(state) is None


def test_react_hallucinated_done_without_tool_is_guarded() -> None:
    """反幻觉：模型未调工具即 done=true（thought 声称成功）→ 拦截，幻觉正文不得回显。"""
    gateway = _ScriptGateway([_HALLUCINATED_DONE])
    events = _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable("用 write 工具把 g.txt 内容改为 beta"),
    )
    # 幻觉正文（"更新为 beta"）不得作为助手消息回显
    texts = [
        str(event.get("payload", {}).get("text") or "")
        for event in _pending_events(events)
        if event.get("kind") == "assistant_message"
    ]
    assert not any("更新为 beta" in text for text in texts)
    # 模型被迫再次调用（幻觉 done 被拦截后回环）
    assert len(gateway.calls) >= 2


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
    # 首轮与回填后的第二轮都走原生工具流，不再先 invoke 再 stream。
    assert gateway.calls == []
    assert len(gateway.stream_calls) == 2
    # 第二轮模型可见标准 assistant ToolCall + 两条对应 role=tool 结果，非 Observation 拼接。
    # read 结果正文带元数据头（范围/总行数/已读完），随后是文件原文。
    native_messages = gateway.stream_calls[1].messages[-3:]
    assert native_messages[0]["role"] == "assistant"
    assert [call["call_id"] for call in native_messages[0]["tool_calls"]] == ["call_read_a", "call_read_b"]
    assert [message["tool_call_id"] for message in native_messages[1:]] == ["call_read_a", "call_read_b"]
    for message, expected in zip(native_messages[1:], ["A 文件内容", "B 文件内容"]):
        content = str(message["content"])
        assert content.endswith(expected)
        assert "已读完" in content.split("\n", 1)[0]
    # 完整文件正文和凭据均不得沿 RunnableConfig 传入模型网关。
    assert gateway.configs == []
    assert gateway.stream_configs == [{"configurable": {}}, {"configurable": {}}]
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
    assert gateway.stream_calls[1].tools
    custom = [
        chunk
        for mode, chunk in events
        if mode == "custom" and chunk.get("kind") == "content"
    ]
    # 首轮包含 ToolCall 的草稿正文不能先于真实工具结果投影；仅保留工具完成后
    # 第二轮收敛回答的原始流式分块。
    assert [(chunk["kind"], chunk["text"]) for chunk in custom] == [
        ("content", "两个文件的共同结论是："),
        ("content", "都可用于后续评测。"),
    ]


def test_native_read_returns_1000_line_txt_in_one_call() -> None:
    """1000 行、含 8000 字符超长行的 .txt 一次 read 读完，第二轮模型可见全文。

    覆盖 txt/md 附件懒加载链路：附件 staged 进工作区后，模型 read 相对路径
    即可在单次工具调用内拿全正文，不受全局 8000 字符工具结果上限影响。
    """
    lines = []
    for i in range(1000):
        if i % 20 == 19:
            lines.append(f"LONG_LINE_{i + 1}:" + "x" * 8000)
        else:
            lines.append(f"LINE_{i + 1:04d}: normal content")
    body = "\n".join(lines) + "\n"
    assert len(body) > 100_000  # 远超旧 8000 字符工具结果上限

    gateway = _NativeToolCallGateway()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write(body)
        with open(f"{tmp}/b.txt", "w", encoding="utf-8") as handle:
            handle.write("B 文件内容")
        agent = LangGraphAgent(
            gateway,
            build_default_registry(),
            sandbox_dir=tmp,
        )
        events = _collect(
            agent,
            _serializable(),
            {
                "configurable": {
                    "thread_id": "read-1000-lines-test",
                    "credentials": {"api_key": "test-secret"},
                }
            },
        )

    pending = _pending_events(events)
    results = [event["payload"] for event in pending if event["kind"] == "tool_result"]
    read_results = [payload for payload in results if payload["name"] == "read"]
    assert read_results and all(payload["ok"] is True for payload in read_results)
    # 第二轮模型输入中的 tool 消息承载全文：无截断标记、包含末行。
    tool_messages = [
        message
        for message in gateway.stream_calls[1].messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call_read_a"
    ]
    assert tool_messages
    content = str(tool_messages[0]["content"])
    # 元数据头 + 全文：头部声明范围/总行数/已读完，正文完整无截断。
    assert content.endswith(body)
    first_line = content.split("\n", 1)[0]
    assert "已读完" in first_line and "共 1000 行" in first_line
    assert "LONG_LINE_1000:" in content
    assert "截断" not in content and "未读完" not in content
    # turn 级观测指标随 assistant_message 事件输出：轮数/工具计数/用量。
    stats_events = [
        event["payload"].get("turn_stats")
        for event in _pending_events(events)
        if event["kind"] == "assistant_message"
    ]
    assert stats_events and stats_events[-1]
    stats = stats_events[-1]
    assert stats["tool_calls"] == 2  # a.txt + b.txt 两次 read
    assert stats["tool_failures"] == 0
    assert stats["model_calls"] >= 2
    assert "prompt_tokens" in stats and "completion_tokens" in stats


def test_native_read_repeat_replays_cached_result() -> None:
    """只读重复调用缓存回放：模型拿到与上次一致的内容，不执行工具。"""

    class _RepeatThenAnswerGateway:
        def __init__(self) -> None:
            self.stream_calls: list[object] = []

        def invoke(self, request: object, config: dict | None = None):
            raise AssertionError("native 路径应走 stream")

        def stream(self, request: object, config: dict | None = None):
            self.stream_calls.append(request)
            has_tools = bool(getattr(request, "tools", ()))
            round_no = len(self.stream_calls)
            if has_tools and round_no <= 2:
                call = NativeToolCall(f"call_read_{round_no}", "read", {"path": "a.txt"})
                response = ModelResponse(text="", latency_ms=1, tool_calls=(call,))
                return iter(
                    [
                        ModelStreamEvent(kind="tool_call", tool_call=call),
                        ModelStreamEvent(kind="completed", response=response),
                    ]
                )
            return iter(
                [
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(text="已根据文件内容作答。", latency_ms=1),
                    )
                ]
            )

    gateway = _RepeatThenAnswerGateway()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello cached")
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )

    kinds = [event["kind"] for event in _pending_events(events)]
    # 只执行第一次 read；重复调用不执行、不产生工具事件。
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds.count("error") == 0
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    # 第三轮模型输入包含被回放的缓存正文（两条 tool 消息内容一致）。
    tool_contents = [
        str(message.get("content") or "")
        for message in gateway.stream_calls[2].messages
        if message.get("role") == "tool"
    ]
    assert len(tool_contents) == 2
    assert all("hello cached" in content for content in tool_contents)
    assert tool_contents[0] == tool_contents[1]
def test_native_web_tools_emit_toolcall_cards_contract() -> None:
    """网页原生工具必须先发完整 ToolCall，再以相同 call_id 发 tool_result。"""

    class _WebToolGateway:
        """首轮返回两个网页工具调用，后续返回无工具收尾响应。"""

        def __init__(self) -> None:
            self.calls: list[object] = []

        def invoke(self, request: object, config: dict | None = None):
            self.calls.append(request)
            if len(self.calls) == 1:
                return ModelResponse(
                    text="",
                    latency_ms=1,
                    tool_calls=(
                        NativeToolCall(
                            "call_web_search",
                            "web_search",
                            {"query": "Firecrawl"},
                        ),
                        NativeToolCall(
                            "call_web_fetch",
                            "web_fetch",
                            {"url": "http://127.0.0.1/", "format": "text"},
                        ),
                    ),
                )
            return ModelResponse(text="网页工具结果已处理。", latency_ms=1)

    gateway = _WebToolGateway()
    events = _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable("搜索并抓取网页", tool_call_mode="native"),
    )

    pending = _pending_events(events)
    calls = [event["payload"] for event in pending if event["kind"] == "tool_call"]
    results = [event["payload"] for event in pending if event["kind"] == "tool_result"]
    assert [payload["call_id"] for payload in calls] == [
        "call_web_search",
        "call_web_fetch",
    ]
    assert [payload["name"] for payload in calls] == ["web_search", "web_fetch"]
    assert [payload["call_id"] for payload in results] == [
        "call_web_search",
        "call_web_fetch",
    ]
    assert [payload["name"] for payload in results] == ["web_search", "web_fetch"]
    assert {tool["name"] for tool in gateway.calls[0].tools} >= {
        "web_search",
        "web_fetch",
    }


def test_native_basic_tools_keep_toolcall_cards_on_validation_error() -> None:
    """全部基础工具即使参数校验失败，也须按原 call_id 回传 ToolCall 结果卡。"""

    class _BasicToolGateway:
        """首轮返回全部基础工具的缺参调用，避免测试访问外部或修改工作区。"""

        def __init__(self) -> None:
            self.calls: list[object] = []

        def invoke(self, request: object, config: dict | None = None):
            self.calls.append(request)
            if len(self.calls) == 1:
                return ModelResponse(
                    text="",
                    latency_ms=1,
                    tool_calls=tuple(
                        NativeToolCall(f"call_{name}", name, {})
                        for name in (
                            "read",
                            "write",
                            "edit",
                            "bash",
                            "task",
                            "web_search",
                            "web_fetch",
                        )
                    ),
                )
            return ModelResponse(text="基础工具结果已处理。", latency_ms=1)

    gateway = _BasicToolGateway()
    events = _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable("读取文件", tool_call_mode="native"),
    )

    pending = _pending_events(events)
    calls = [event["payload"] for event in pending if event["kind"] == "tool_call"]
    results = [event["payload"] for event in pending if event["kind"] == "tool_result"]
    expected_names = [
        "read",
        "write",
        "edit",
        "bash",
        "task",
        "web_search",
        "web_fetch",
    ]
    assert [payload["name"] for payload in calls] == expected_names
    assert [payload["call_id"] for payload in calls] == [
        f"call_{name}" for name in expected_names
    ]
    assert [payload["name"] for payload in results] == expected_names
    assert [payload["call_id"] for payload in results] == [
        f"call_{name}" for name in expected_names
    ]
    assert all(payload["ok"] is False for payload in results)
    assert {tool["name"] for tool in gateway.calls[0].tools} >= set(expected_names)


def test_native_read_repeat_same_offset_is_blocked() -> None:
    """原生 ToolCall 路径同样拦截相同 offset 的重复 read。"""

    class _RepeatReadGateway:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def invoke(self, request: object, config: dict | None = None):
            self.calls.append(request)
            if getattr(request, "tools", ()) == ():
                return ModelResponse(text="已根据文件内容作答。", latency_ms=1)
            return ModelResponse(
                text="",
                latency_ms=1,
                tool_calls=(
                    NativeToolCall(
                        f"call_read_{len(self.calls)}",
                        "read",
                        {"path": "a.txt"},
                    ),
                ),
            )

        def stream(self, request: object, config: dict | None = None):
            if getattr(request, "tools", ()):
                response = self.invoke(request, config)
                events = [
                    ModelStreamEvent(kind="tool_call", tool_call=call)
                    for call in response.tool_calls
                ]
                events.append(ModelStreamEvent(kind="completed", response=response))
                return iter(events)
            return iter(
                [
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(text="已根据文件内容作答。", latency_ms=1),
                    )
                ]
            )

    gateway = _RepeatReadGateway()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("tool_call") == 1
    assert kinds.count("error") == 0
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_native_tool_calls_delay_draft_content_until_tool_result() -> None:
    """P1：native 同轮 ToolCall 的草稿正文必须等待工具终态，不能抢先展示。"""
    gateway = _NativeToolCallGateway()
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
    # ToolCall 前的模型草稿不再落 assistant_message；仅工具结束后的最终回答可交付。
    assert messages
    assert all(event["payload"].get("interim") is not True for event in messages)
    assert all(event["payload"].get("text") != "先读取两个附件再汇总" for event in messages)
    # 首轮草稿不得以正文增量抢在 ToolCard 前显示；浏览器只能在工具终态后收到
    # 第二轮收敛回答，杜绝「已完成」类叙述先于实际执行结果的矛盾。
    first_content = next(
        index
        for index, (mode, chunk) in enumerate(events)
        if mode == "custom" and chunk.get("kind") == "content"
    )
    first_tool_call = next(
        index
        for index, (mode, chunk) in enumerate(events)
        if mode == "updates"
        and any(event["kind"] == "tool_call" for event in iter_pending_events(chunk))
    )
    assert first_tool_call < first_content


def test_native_read_then_write_refills_in_original_call_order() -> None:
    """P2：同轮 read+write 串行执行，模型回填顺序与原始 call_id 一致。"""

    class _ReadWriteGateway:
        def __init__(self) -> None:
            self.stream_calls: list[object] = []

        def stream(self, request: object, config: dict | None = None):
            self.stream_calls.append(request)
            if len(self.stream_calls) == 1:
                calls = (
                    NativeToolCall("call_read", "read", {"path": "a.txt"}),
                    NativeToolCall(
                        "call_write",
                        "write",
                        {"path": "out.txt", "content": "from-read"},
                    ),
                )
                return iter(
                    [
                        ModelStreamEvent(kind="tool_call", tool_call=calls[0]),
                        ModelStreamEvent(kind="tool_call", tool_call=calls[1]),
                        ModelStreamEvent(
                            kind="completed",
                            response=ModelResponse(text="", latency_ms=1, tool_calls=calls),
                        ),
                    ]
                )
            return iter(
                [
                    ModelStreamEvent(kind="content", text="已完成读写"),
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(text="已完成读写", latency_ms=1),
                    ),
                ]
            )

    gateway = _ReadWriteGateway()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("source")
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
        assert os.path.isfile(os.path.join(tmp, "out.txt"))

    pending = _pending_events(events)
    calls = [event["payload"]["call_id"] for event in pending if event["kind"] == "tool_call"]
    results = [event["payload"]["call_id"] for event in pending if event["kind"] == "tool_result"]
    assert calls == ["call_read", "call_write"]
    assert results == ["call_read", "call_write"]
    native_messages = gateway.stream_calls[1].messages[-3:]
    assert native_messages[0]["role"] == "assistant"
    assert [call["call_id"] for call in native_messages[0]["tool_calls"]] == [
        "call_read",
        "call_write",
    ]
    assert [message["tool_call_id"] for message in native_messages[1:]] == [
        "call_read",
        "call_write",
    ]


def test_native_stream_associate_error_trips_after_two_rounds(monkeypatch) -> None:
    """流式空 call_id 每回合只记一笔终态；连续两笔关联错乱触发脚踢。

    旧实现先记成功流再记 associate，连续事故永远 0→1，rounds 会变成 4。
    """
    from app.harness.execution.stream_metrics import StreamMetrics

    metrics = StreamMetrics(failure_threshold=2, cooldown_s=60.0)
    monkeypatch.setattr("app.agent.react.get_default_stream_metrics", lambda: metrics)

    class _InvalidStreamGateway:
        def invoke(self, _request: object, config: dict | None = None):
            raise AssertionError("有 stream 时不应回退 invoke")

        def stream(self, _request: object, config: dict | None = None):
            calls = (
                NativeToolCall("", "read", {"path": "a.txt"}),
                NativeToolCall("second", "read", {"path": "b.txt"}),
            )
            return iter(
                [
                    ModelStreamEvent(kind="content", text="准备读取"),
                    *(ModelStreamEvent(kind="tool_call", tool_call=call) for call in calls),
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(
                            text="准备读取", latency_ms=1, tool_calls=calls
                        ),
                    ),
                ]
            )

    for _ in range(2):
        events = _collect(
            LangGraphAgent(_InvalidStreamGateway(), build_default_registry()),
            _serializable(),
        )
        pending = _pending_events(events)
        assert [event["kind"] for event in pending] == ["error"]
        assert pending[0]["payload"]["code"] == "UPSTREAM"

    snap = metrics.snapshot()
    assert snap["stream"]["rounds"] == 2
    assert snap["stream"]["associate_errors"] == 2
    assert metrics.is_parallel_disabled() is True


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


def test_native_stream_kill_switch_uses_invoke(monkeypatch) -> None:
    """P4：关闭 native 流式开关后走 invoke，不调用 stream。"""
    from app.config import settings
    from app.harness.execution.stream_metrics import get_default_stream_metrics

    monkeypatch.setattr(settings, "agent_native_stream_enabled", False)
    get_default_stream_metrics().reset()
    gateway = _NativeToolCallGateway()
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("A")
        with open(f"{tmp}/b.txt", "w", encoding="utf-8") as handle:
            handle.write("B")
        _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    assert gateway.stream_calls == []
    assert gateway.calls
    assert get_default_stream_metrics().snapshot()["stream"]["invoke_fallbacks"] >= 1


def test_legacy_profile_does_not_send_native_tools() -> None:
    """不支持 tools 的协议档走严格 JSON ReAct，避免上游请求先于回退失败。"""
    gateway = _ScriptGateway([_REACT_DONE])
    _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable(tool_call_mode="legacy"),
    )
    assert gateway.calls[0].tools == ()
    assert "每轮输出严格 JSON" in gateway.calls[0].system


def test_native_stream_json_react_read_feeds_file_content() -> None:
    """native 流式下模型若只输出 JSON ReAct，read 正文必须回填下一轮，且协议 JSON 不出站。"""
    react_read = (
        '{"protocol": "react", "version": "react.v1", '
        '"thought": "用户需要总结附件 11.txt 的内容。", '
        '"tool": "read", "arguments": {"path": "attachments/11.txt", '
        '"offset": 0, "limit": 200}, "done": false}'
    )
    file_body = "FILE_BODY_UNIQUE_11TXT 这是附件正文，模型必须看见。"

    class _JsonReactNativeGateway:
        def __init__(self) -> None:
            self.stream_calls: list[object] = []

        def invoke(self, _request: object, config: dict | None = None):
            raise AssertionError("native 流式 JSON ReAct 不应回退 invoke")

        def stream(self, request: object, config: dict | None = None):
            self.stream_calls.append(request)
            if len(self.stream_calls) == 1:
                return iter(
                    [
                        ModelStreamEvent(kind="content", text=react_read),
                        ModelStreamEvent(
                            kind="completed",
                            response=ModelResponse(text=react_read, latency_ms=1),
                        ),
                    ]
                )
            return iter(
                [
                    ModelStreamEvent(kind="content", text="附件主要内容是："),
                    ModelStreamEvent(kind="content", text=file_body),
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(
                            text="附件主要内容是：" + file_body, latency_ms=2
                        ),
                    ),
                ]
            )

    gateway = _JsonReactNativeGateway()
    with tempfile.TemporaryDirectory() as tmp:
        attach_dir = os.path.join(tmp, "attachments")
        os.makedirs(attach_dir)
        with open(os.path.join(attach_dir, "11.txt"), "w", encoding="utf-8") as handle:
            handle.write(file_body)
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable("帮我读取附件 11.txt"),
            {"configurable": {"thread_id": "json-react-native-read"}},
        )

    assert len(gateway.stream_calls) == 2
    second = gateway.stream_calls[1]
    tool_texts = [
        str(message.get("content") or "")
        for message in second.messages
        if str(message.get("role") or "") == "tool"
    ]
    assert tool_texts, "JSON ReAct read 必须回填为 role=tool"
    assert any(file_body in text for text in tool_texts)
    leaked = [
        chunk.get("text") or ""
        for mode, chunk in events
        if mode == "custom" and chunk.get("kind") == "content"
    ]
    assert not any('"protocol"' in text and "react" in text for text in leaked)
    pending = _pending_events(events)
    assert any(event["kind"] == "tool_call" for event in pending)
    assert any(
        event["kind"] == "tool_result" and event["payload"].get("ok") is True
        for event in pending
    )


def test_react_preserves_configured_system_prompt() -> None:
    """ReAct 必须保留 ws.py 注入的系统提示词，再按 CX-4 装配工具约束。"""
    gateway = _ScriptGateway([_REACT_DONE])
    _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable(system="【自定义平台规则】读取后必须先总结。"),
    )
    system = gateway.calls[0].system
    assert "【自定义平台规则】读取后必须先总结。" in system
    assert "【本轮可用平台工具】" in system
    assert system.index("【自定义平台规则】") < system.index("【可见技能】")
    assert system.index("【可见技能】") < system.index("【当前阶段】")
    names = {item["name"] for item in gateway.calls[0].tools}
    assert "read" in names
    assert "task.create" not in names


def test_react_assemble_injects_compact_summary() -> None:
    """CX-4：configurable.session.compact_summary 装配到【会话摘要】。"""
    gateway = _ScriptGateway([_REACT_DONE])
    _collect(
        LangGraphAgent(gateway, build_default_registry()),
        _serializable(system="【Persona】评测助手"),
        config={"configurable": {"session": {"compact_summary": "此前已完成基准评测规划"}}},
    )
    system = gateway.calls[0].system
    assert "【会话摘要】" in system
    assert "此前已完成基准评测规划" in system
    assert system.index("【Persona】") < system.index("【可见技能】")
    assert system.index("【可见技能】") < system.index("【会话摘要】")
    assert system.index("【会话摘要】") < system.index("【当前阶段】")


def test_react_done_immediately() -> None:
    """OR-2：首轮即 done，无工具调用。"""
    gateway = _ScriptGateway([_REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds == ["assistant_message", "response.completed"]
    # done JSON 的 thought 是控制字段；必须另调一轮自然语言回答，不能原样回显。
    assert len(gateway.calls) == 2
    payloads = [
        event["payload"]
        for event in _pending_events(events)
        if event["kind"] == "assistant_message"
    ]
    assert payloads[0]["text"] == "工具结果已整理。"
    assert "已完成检索并总结" not in payloads[0]["text"]


_REACT_WRITE = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要写入文件", '
    '"tool": "write", "arguments": {"path": "b.txt", "content": "x"}, "done": false}'
)
_REACT_EDIT = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要编辑文件", '
    '"tool": "edit", "arguments": {"path": "b.txt", "old": "x", "new": "y"}, "done": false}'
)
_REACT_WEB_SEARCH = (
    '{"protocol": "react", "version": "react.v1", "thought": "需要联网搜索", '
    '"tool": "web_search", "arguments": {"query": "ReAct 原理"}, "done": false}'
)


def test_tools_route_ends_when_budget_exhausted() -> None:
    """工具回边：队列未空继续；预算耗尽或回合失败必须 END，不能再进模型。"""
    from app.agent.react import tools_route

    assert (
        tools_route(
            {
                "pending_tool": {"name": "read"},
                "budget": {"model_calls": 0, "tool_turns": 0},
            }
        )
        == "tools"
    )
    assert tools_route({"pending_tool": None, "budget": {"model_calls": 0, "tool_turns": 1}}) == "end"
    assert tools_route({"pending_tool": None, "budget": {"model_calls": 3, "tool_turns": 0}}) == "end"
    assert (
        tools_route(
            {
                "pending_tool": None,
                "turn_failed": True,
                "budget": {"model_calls": 3, "tool_turns": 3},
            }
        )
        == "end"
    )
    assert (
        tools_route({"pending_tool": None, "budget": {"model_calls": 3, "tool_turns": 3}})
        == "react_agent"
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

    read 相同窗口只执行一次（见 test_react_read_repeat_blocked_after_first_success）；
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
    # 纠正环节只留在内部 Observation，不再生成过程卡。
    assert kinds.count("thought") == 0


def test_react_read_repeat_blocked_after_first_success() -> None:
    """OR-4：相同 offset 的 read 只执行一次，第二次纠正后模型 done 收尾。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway([_REACT_READ, _REACT_READ, _REACT_DONE])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_react_web_search_repeat_blocked_after_first_success(monkeypatch) -> None:
    """OR-4：相同 query 的 web_search 只执行一次，第二次纠正后模型 done 收尾。

    回归：READONLY_TOOLS 曾漏收 web_search，导致相同关键词重复搜索不被拦截。
    """
    from app.harness.execution import dispatch
    from app.harness.execution.dispatch import WebSearchResult

    def fake_search(
        query: str, *, limit: object | None = None, timeout_s: float = 20.0
    ) -> WebSearchResult:
        return WebSearchResult(
            query=query,
            results=({"title": "ReAct", "url": "https://example.com/react", "description": "推理与行动"},),
        )

    monkeypatch.setattr(dispatch, "web_search", fake_search)
    gateway = _ScriptGateway([_REACT_WEB_SEARCH, _REACT_WEB_SEARCH, _REACT_DONE])
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_native_web_search_repeat_same_query_is_blocked(monkeypatch) -> None:
    """原生 ToolCall 路径同样拦截相同 query 的重复 web_search。"""
    from app.harness.execution import dispatch
    from app.harness.execution.dispatch import WebSearchResult

    def fake_search(
        query: str, *, limit: object | None = None, timeout_s: float = 20.0
    ) -> WebSearchResult:
        return WebSearchResult(
            query=query,
            results=({"title": "ReAct", "url": "https://example.com/react", "description": "推理与行动"},),
        )

    monkeypatch.setattr(dispatch, "web_search", fake_search)

    class _RepeatSearchGateway:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def invoke(self, request: object, config: dict | None = None):
            self.calls.append(request)
            if getattr(request, "tools", ()) == ():
                return ModelResponse(text="已根据搜索结果作答。", latency_ms=1)
            return ModelResponse(
                text="",
                latency_ms=1,
                tool_calls=(
                    NativeToolCall(
                        f"call_search_{len(self.calls)}",
                        "web_search",
                        {"query": "ReAct"},
                    ),
                ),
            )

        def stream(self, request: object, config: dict | None = None):
            if getattr(request, "tools", ()):
                response = self.invoke(request, config)
                events = [
                    ModelStreamEvent(kind="tool_call", tool_call=call)
                    for call in response.tool_calls
                ]
                events.append(ModelStreamEvent(kind="completed", response=response))
                return iter(events)
            return iter(
                [
                    ModelStreamEvent(
                        kind="completed",
                        response=ModelResponse(text="已根据搜索结果作答。", latency_ms=1),
                    )
                ]
            )

    gateway = _RepeatSearchGateway()
    events = _collect(LangGraphAgent(gateway, build_default_registry()), _serializable())
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("tool_call") == 1
    assert kinds.count("error") == 0
    assert kinds[-2:] == ["assistant_message", "response.completed"]


def test_read_offset_aliases_normalize_to_same_call() -> None:
    """缺省 offset、offset=0 与 next_offset=0 视为同一窗口，避免漏拦重复读。"""
    from app.agent.react import _normalized_tool_arguments

    missing = _normalized_tool_arguments("read", {"path": "a.txt"})
    explicit = _normalized_tool_arguments("read", {"path": "a.txt", "offset": 0})
    alias = _normalized_tool_arguments("read", {"path": "a.txt", "next_offset": 0})
    assert missing == explicit == alias == {"path": "a.txt", "offset": 0}


def test_split_native_readonly_repeats_dedups_same_batch() -> None:
    """同一响应内相同 path+offset 只保留第一次，bash 等写工具不受影响。"""
    from app.agent.react import _split_native_readonly_repeats

    first = NativeToolCall(call_id="1", name="read", arguments={"path": "a.txt"})
    alias = NativeToolCall(call_id="2", name="read", arguments={"path": "a.txt", "next_offset": 0})
    later = NativeToolCall(call_id="3", name="read", arguments={"path": "a.txt", "offset": 40})
    bash = NativeToolCall(call_id="4", name="bash", arguments={"command": "ls"})
    allowed, skipped, runs = _split_native_readonly_repeats(
        {"observations": []},
        (first, alias, later, bash),
    )
    assert [call.call_id for call in allowed] == ["1", "3", "4"]
    assert skipped is not None and skipped.call_id == "2"
    assert runs == 1


def test_split_native_readonly_repeats_dedups_web_search() -> None:
    """同一响应内相同 query 的 web_search 只保留第一次（OR-4 同批去重）。"""
    from app.agent.react import _split_native_readonly_repeats

    first = NativeToolCall(call_id="1", name="web_search", arguments={"query": "ReAct"})
    alias = NativeToolCall(call_id="2", name="web_search", arguments={"query": "ReAct"})
    later = NativeToolCall(call_id="3", name="web_search", arguments={"query": "LangGraph"})
    allowed, skipped, runs = _split_native_readonly_repeats(
        {"observations": []},
        (first, alias, later),
    )
    assert [call.call_id for call in allowed] == ["1", "3"]
    assert skipped is not None and skipped.call_id == "2"
    assert runs == 1


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
                "文件内容已用于完成分析；建议继续按需求核对。",
            ]
        )
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    assert kinds.count("tool_call") == 1
    assert kinds[-2:] == ["assistant_message", "response.completed"]
    final = [
        e["payload"].get("text", "") for e in _pending_events(events) if e["kind"] == "assistant_message"
    ]
    assert final == ["文件内容已用于完成分析；建议继续按需求核对。"]
    assert all("hello" not in message for message in final)
    assert gateway.calls[-1].tools == ()


def test_react_read_toolname_with_newline_still_normalized() -> None:
    """strip 兜底：工具名带尾随换行仍识别为 read，重复相同窗口只执行一次。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(f"{tmp}/a.txt", "w", encoding="utf-8") as handle:
            handle.write("hello")
        gateway = _ScriptGateway([_REACT_READ_NL, _REACT_READ_NL, _REACT_DONE])
        events = _collect(
            LangGraphAgent(gateway, build_default_registry(), sandbox_dir=tmp),
            _serializable(),
        )
    kinds = [event["kind"] for event in _pending_events(events)]
    assert kinds.count("error") == 0
    messages = [event["payload"].get("message", "") for event in _pending_events(events)]
    assert not any("连续调用" in message for message in messages)
    assert not any("未注册" in message for message in messages)
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
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
    # 模型调用 3 次：首次输出坏 JSON 被纠正，第二次 done 后另调自然语言收尾。
    assert len(gateway.calls) == 3
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


def test_hydrate_native_messages_clips_overlong_tool_result() -> None:
    """原生 ToolResult 回传模型时按统一上限截断，避免预填充超时。"""
    from app.agent.react import _hydrate_native_messages
    from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS
    from app.harness.execution import NativeToolResultStore

    store = NativeToolResultStore()
    store.put("t1", "c1", "x" * (MODEL_TOOL_RESULT_MAX_CHARS + 800))
    hydrated = _hydrate_native_messages(
        {
            "native_messages": [
                {"role": "tool", "tool_call_id": "c1", "name": "bash", "content": ""},
            ]
        },
        store,
        "t1",
    )
    content = str(hydrated[0]["content"])
    assert "截断" in content
    assert len(content) < MODEL_TOOL_RESULT_MAX_CHARS + 80


def test_hydrate_native_messages_keeps_full_read_result() -> None:
    """read 的 ToolResult 回传模型时不按全局 8000 裁剪，1000 行量级一次可见。"""
    from app.agent.react import _hydrate_native_messages
    from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS
    from app.harness.execution import NativeToolResultStore

    body = "\n".join(f"line-{i:04d}" for i in range(1000)) + "\n"
    assert len(body) > MODEL_TOOL_RESULT_MAX_CHARS
    store = NativeToolResultStore()
    store.put("t1", "c1", body)
    hydrated = _hydrate_native_messages(
        {
            "native_messages": [
                {"role": "tool", "tool_call_id": "c1", "name": "read", "content": ""},
            ]
        },
        store,
        "t1",
    )
    content = str(hydrated[0]["content"])
    assert "截断" not in content
    assert content == body
    assert "line-0999" in content


def test_stage_inputs_forbid_small_page_reads() -> None:
    """阶段输入必须引导模型省略 limit 一次读完，避免拆小页连续多次读取。"""
    from app.agent.react import NATIVE_TOOL_STAGE_INPUT, REACT_STAGE_INPUT

    assert "省略 limit" in REACT_STAGE_INPUT
    assert "禁止人为拆成多个小页" in REACT_STAGE_INPUT
    assert "省略 limit" in NATIVE_TOOL_STAGE_INPUT
    assert "禁止人为拆成多个小页" in NATIVE_TOOL_STAGE_INPUT


def test_read_tool_description_recommends_one_shot_read() -> None:
    """read 工具描述与 limit 参数说明都带一次读完的正向引导（结构化约束）。"""
    registry = build_default_registry()
    definition = registry.get("read")
    assert "省略 limit 一次读完" in definition.description
    assert "禁止人为拆成" in definition.description
    limit_schema = definition.parameters_schema["properties"]["limit"]
    assert "建议省略" in str(limit_schema.get("description") or "")
    assert limit_schema.get("maximum") == 2000


def _observation(tool: str, text: str) -> object:
    """构造观察注入用例用的最小 Observation。"""
    from app.harness.contracts import Observation

    return Observation(tool=tool, text=text, ok=True)


def test_inject_observations_keeps_all_read_pages() -> None:
    """read 观察不受最近 6 条条数上限；非 read 观察仍只注入最近 6 条。"""
    from app.agent.react import _inject_observations

    observations = []
    for i in range(8):
        observations.append(_observation("read", f"READ_PAGE_{i}"))
        observations.append(_observation("bash", f"BASH_OUT_{i}"))
    text = _inject_observations({"observations": observations})
    # 8 页 read 全部保留（旧逻辑只能看到尾部页，导致回答内容不全）
    for i in range(8):
        assert f"READ_PAGE_{i}" in text
    # 非 read 观察只保留最近 6 条，最早的 2 条被丢弃
    assert "BASH_OUT_0" not in text
    assert "BASH_OUT_1" not in text
    for i in range(2, 8):
        assert f"BASH_OUT_{i}" in text
    # 时序不被打乱：第 0 页在第 7 页之前
    assert text.index("READ_PAGE_0") < text.index("READ_PAGE_7")


def test_inject_observations_read_budget_drops_oldest_pages(monkeypatch) -> None:
    """read 总字符熔断超预算时丢最早的页，较新的页优先保留。"""
    import app.agent.react as react_module

    monkeypatch.setattr(react_module, "INJECT_READ_TOTAL_MAX_CHARS", 300)
    observations = [
        _observation("read", "PAGE_OLD_" + "a" * 200),
        _observation("read", "PAGE_MID_" + "b" * 200),
        _observation("read", "PAGE_NEW_" + "c" * 200),
    ]
    text = react_module._inject_observations({"observations": observations})
    assert "PAGE_OLD_" not in text
    assert "PAGE_NEW_" in text


def test_inject_observations_web_fetch_full_budget() -> None:
    """web_fetch 观察按 WEB_FETCH_MAX_CHARS 预算注入（2026-08-28 调整）。

    旧全局 8000 字符预算会把 2 万字符的长文截成带 ``[截断]`` 标记的半篇；
    放宽后整段正文应原样进入模型上下文。
    """
    import app.agent.react as react_module

    long_text = "Z" * 20_000
    text = react_module._inject_observations(
        {"observations": [_observation("web_fetch", long_text)]}
    )
    assert long_text in text
    assert "[截断]" not in text
