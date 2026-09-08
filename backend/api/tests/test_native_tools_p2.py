"""F0/P2 原生循环测试（《Agent 原生工具装配方案》V0.2 §5 P2 验收）。

覆盖：orchestrator 原生 Act（tool_use 名守卫/重复守卫/round 缓冲/多工具入队）、
Observe 回填组装（store 正文合成、正文缺失降级、占位观察跳过注入、回填截断）、
图级原生全链（tool_use → toolnode 真实执行 read → role=tool 正文回填 → 文本
收尾）、多 tool_calls 队列自环 drain、越权 tool_use fail-closed、persistent
契约（中间往返不落 Message/窗口，正文只经 store）。不依赖 WS/DB。
"""

from __future__ import annotations

import asyncio

from app.agent import LangGraphAgent
from app.agent.taor_nodes import _build_native_backfill, _observation_lines
from app.config import settings
from app.harness.execution.native_results import NativeToolResultStore
from app.harness.memory import SerializableRequest
from app.llm import ModelResponse, NativeToolCall

_PLAN_OK = (
    '{"intent":"排查并定位测试报告失败原因","skill_id":null,'
    '"slots":{"steps":["读取报告","定位失败用例","给出结论"]},'
    '"tools_needed":["read"],"delivery":"chat",'
    '"budget":{"model_calls":6,"tool_turns":4},"allows_replan":false,'
    '"notes":"测试用计划","protocol":"plan","version":"plan.v1"}'
)
_REACT_DONE = (
    '{"thought":"已定位原因","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n找到原因：数据集样本量不足。'
)
_REFLECT_PASS = (
    '{"verdict":"pass","reason":"候选答复可直接给出",'
    '"clarify_question":null,"repair_hint":null,'
    '"protocol":"reflect","version":"reflect.v1"}'
)
_TOOL_CALL_READ = NativeToolCall(
    call_id="call-1", name="read", arguments={"path": "result.md"}
)
_TOOL_CALL_READ_B = NativeToolCall(
    call_id="call-2", name="read", arguments={"path": "notes.md"}
)


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "anthropic_messages",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


def _config(tmp_path, thread_id: str) -> dict:
    return {
        "configurable": {
            "credentials": {"api_key": ""},
            "thread_id": thread_id,
            "sandbox": {"dir": str(tmp_path)},
        }
    }


class _ScriptedNativeGateway:
    """按调用序号返回 str（文本）或 ModelResponse（原生 tool_use）；记录请求。"""

    def __init__(self, *items):
        self._items = list(items)
        self.calls = 0
        self.requests: list[object] = []

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        if self.calls >= len(self._items):
            raise AssertionError(f"模型调用超出脚本：第 {self.calls} 次")
        self.requests.append(request)
        item = self._items[self.calls]
        self.calls += 1
        if isinstance(item, ModelResponse):
            return item
        return ModelResponse(text=str(item), usage={}, latency_ms=0)


def _engine_on(monkeypatch):
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")


def _collect(agent: LangGraphAgent, request: SerializableRequest, config: dict):
    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(request, config=config):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _node_trace(events: list[tuple[str, dict]]) -> list[str]:
    return [
        node
        for mode, chunk in events
        if mode == "updates"
        for node in chunk
        if node in {"plan", "discover", "orchestrator", "tools", "reflect"}
    ]


def _all_pending(events: list[tuple[str, dict]]) -> list[dict]:
    return [
        event
        for mode, chunk in events
        if mode == "updates"
        for value in chunk.values()
        if isinstance(value, dict)
        for event in value.get("pending_events", [])
    ]


# ─── 1. 回填组装纯函数（Observe 消费端）───


def test_backfill_assembles_assistant_and_tool_pairs() -> None:
    """store 有正文 → 合成 assistant(tool_calls)+role=tool 对，正文透传（内部规范）。"""
    store = NativeToolResultStore()
    store.put("thread-1", "call-1", "文件正文：样本量不足")
    native_round = {
        "assistant": {
            "role": "assistant",
            "content": "我先读取报告。",
            "tool_calls": [{"call_id": "call-1", "name": "read", "arguments": {"path": "result.md"}}],
        }
    }
    backfill = _build_native_backfill(native_round, store, "thread-1")
    assert backfill[0]["role"] == "assistant"
    assert backfill[0]["tool_calls"][0]["call_id"] == "call-1"
    assert backfill[1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "read",
        "content": "文件正文：样本量不足",
    }


def test_backfill_missing_store_uses_explicit_placeholder() -> None:
    """store 正文缺失（跨进程 resume/写入失败）→ 显式降级文案（不伪造正文）。"""
    native_round = {
        "assistant": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"call_id": "gone", "name": "read", "arguments": {"path": "a.md"}}],
        }
    }
    backfill = _build_native_backfill(native_round, NativeToolResultStore(), "thread-1")
    assert "不可用" in backfill[1]["content"]
    assert "gone" in backfill[1]["tool_call_id"]


def test_backfill_clips_oversized_content() -> None:
    """store 内 600K 级正文在回填层二次裁剪并带截断标注（R1-M4 预算）。"""
    store = NativeToolResultStore()
    store.put("t", "c1", "x" * 70000)
    native_round = {
        "assistant": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"call_id": "c1", "name": "read", "arguments": {"path": "big.md"}}],
        }
    }
    backfill = _build_native_backfill(native_round, store, "t")
    content = backfill[1]["content"]
    assert len(content) <= 60000 + 200
    assert "回填已截断" in content


def test_observation_lines_skip_native_placeholders() -> None:
    """原生占位观察不注入模型输入；正常/失败观察照常注入（供 repair 提示）。"""
    state = {
        "observations": [
            {"tool": "read", "text": "工具 read 已执行；完整结果仅在当前回合供模型使用。", "ok": True},
            {"tool": "web_search", "text": "检索到 3 条结果…", "ok": True},
        ]
    }
    lines = _observation_lines(state)  # type: ignore[arg-type]
    assert len(lines) == 1
    assert "完整结果仅在当前回合" not in lines[0]
    assert "检索到 3 条结果" in lines[0]


# ─── 2. 图级：原生全链（tool_use → 真实 read 执行 → 正文回填 → 文本收尾）───


def test_native_full_cycle_real_read_backfill(monkeypatch, tmp_path) -> None:
    """P2 主验收：开闸档 tool_use → toolnode 原生执行 read → 下一轮请求携带
    assistant(tool_use)+role=tool 正文对 → 模型按正文文本收尾；事件不重放。"""
    _engine_on(monkeypatch)
    report = tmp_path / "result.md"
    report.write_text("失败原因：样本量不足 500 条", encoding="utf-8")
    gateway = _ScriptedNativeGateway(
        _PLAN_OK,
        ModelResponse(
            text="我将读取报告文件。",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            tool_calls=(_TOOL_CALL_READ,),
        ),
        _REACT_DONE,
        _REFLECT_PASS,
    )
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), _config(tmp_path, "p2-t1"))
    trace = _node_trace(events)
    assert trace == ["plan", "discover", "orchestrator", "tools", "orchestrator", "reflect"]

    # 回填请求（第 3 次模型调用）：原始 user + assistant(tool_use) + role=tool(正文)
    backfill_request = gateway.requests[2]
    messages = list(backfill_request.messages)
    assistant_msg = messages[-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["name"] == "read"
    tool_msg = messages[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call-1"
    assert "样本量不足" in tool_msg["content"]  # store 正文真实回填
    # 原生占位观察未双写：无独立 user 观察帧夹在 assistant/tool 之间
    assert len(messages) == 3

    pending = _all_pending(events)
    kinds = [event["kind"] for event in pending]
    assert kinds.count("tool_call") == 1 and kinds.count("tool_result") == 1  # 不重放
    tool_result = next(e for e in pending if e["kind"] == "tool_result")
    assert tool_result["payload"]["ok"] is True
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["engine"] == "agent"
    assistant = next(e for e in pending if e["kind"] == "assistant_message")
    assert "样本量不足" in assistant["payload"]["text"]
    # usage 回合累计（含原生调用）→ 收尾 turn_stats
    assert assistant["payload"]["turn_stats"]["usage"]["total_tokens"] == 15


def test_native_multi_tool_calls_queue_drains(monkeypatch, tmp_path) -> None:
    """一次 Act 多个 tool_use → tools 自环逐个执行 → 单轮回填含全部 tool 对。"""
    _engine_on(monkeypatch)
    (tmp_path / "result.md").write_text("报告 A：通过", encoding="utf-8")
    (tmp_path / "notes.md").write_text("笔记 B：待补用例", encoding="utf-8")
    gateway = _ScriptedNativeGateway(
        _PLAN_OK,
        ModelResponse(
            text="读取两份文件。",
            usage={},
            tool_calls=(_TOOL_CALL_READ, _TOOL_CALL_READ_B),
        ),
        _REACT_DONE,
        _REFLECT_PASS,
    )
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), _config(tmp_path, "p2-t2"))
    trace = _node_trace(events)
    # tools 自环两次（两个 read 逐个执行）后回 orchestrator
    assert trace == [
        "plan",
        "discover",
        "orchestrator",
        "tools",
        "tools",
        "orchestrator",
        "reflect",
    ]
    pending = _all_pending(events)
    results = [e for e in pending if e["kind"] == "tool_result"]
    assert len(results) == 2
    assert {e["payload"]["call_id"] for e in results} == {"call-1", "call-2"}
    # 回填轮末尾两条 role=tool（顺序与 Act 一致）
    messages = list(gateway.requests[2].messages)
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call-1", "call-2"]
    assert "报告 A" in tool_msgs[0]["content"] and "笔记 B" in tool_msgs[1]["content"]
    assistant_msg = messages[-3]
    assert assistant_msg["role"] == "assistant"
    assert len(assistant_msg["tool_calls"]) == 2


def test_native_out_of_view_tool_use_fails_closed(monkeypatch, tmp_path) -> None:
    """tool_use 伪造越权名（bash，∉ allowed_tools）→ VALIDATION 就地收尾，不执行。"""
    _engine_on(monkeypatch)
    gateway = _ScriptedNativeGateway(
        _PLAN_OK,
        ModelResponse(
            text="",
            usage={},
            tool_calls=(NativeToolCall(call_id="c-x", name="bash", arguments={"command": "id"}),),
        ),
    )
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), _config(tmp_path, "p2-t3"))
    pending = _all_pending(events)
    assert not any(event["kind"] == "tool_result" for event in pending)  # 未执行
    error = next(e for e in pending if e["kind"] == "error")
    assert "非法工具调用：bash" in error["payload"]["message"]
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "error"
    assert gateway.calls == 2  # plan + orchestrator；reflect L1 硬错误不调模型


def test_native_failed_tool_body_backfilled(monkeypatch, tmp_path) -> None:
    """失败工具（文件不存在）→ 错误正文经 store 回填可见（R3-M5：repair 依据）。"""
    _engine_on(monkeypatch)
    gateway = _ScriptedNativeGateway(
        _PLAN_OK,
        ModelResponse(
            text="读取报告。",
            usage={},
            tool_calls=(NativeToolCall(call_id="c-e", name="read", arguments={"path": "missing.md"}),),
        ),
        _REACT_DONE,  # orchestrator#2：回填轮（带失败正文）→ 模型收尾
        _REACT_DONE,  # H4 repair 回灌后 orchestrator#3 再收尾
        _REFLECT_PASS,
    )
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), _config(tmp_path, "p2-t4"))
    # 回填轮请求（orchestrator#2）：role=tool 消息携带失败正文（repair 依据）
    messages = list(gateway.requests[2].messages)
    tool_msg = messages[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c-e"
    # 失败错误正文经 store 回填（toolnode 失败路径 put 的归一错误文本）
    assert "执行失败" in tool_msg["content"] or "NOT_FOUND" in tool_msg["content"]
    # 占位观察不双写（-2 为 assistant 段）
    assert messages[-2]["role"] == "assistant"
    pending = _all_pending(events)
    tool_result = next(e for e in pending if e["kind"] == "tool_result")
    assert tool_result["payload"]["ok"] is False
    assert any(e["kind"] == "response.completed" for e in pending)  # 回合正常收尾
