"""真实七节点图、Runtime、Attempt、历史投影的聚焦契约测试。"""

import asyncio
from copy import deepcopy

import pytest

from app.agent.loop import TurnDependencies, _history_selection, build_agent
from app.agent.loop_settings import LoopSettings
from app.agent.runtime import AgentRuntime, RuntimeClosedError, TurnAlreadyRunningError
from app.harness.memory.agent_messages import derive_messages
from app.llm.loop_contracts import (
    Done,
    LlmRequest,
    LlmRequestError,
    ProtocolState,
    ProviderItemEnd,
    ProviderItemStart,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    ToolSpec,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("selected,indices", [
    (["a", "b", "a"], [0, 1, 2]),
    (["a"], [2]),
    (["a", "a"], [0, 2]),
    ([], []),
])
async def test_history_selection_preserves_order_and_prefers_exact_suffix(selected, indices):
    """完整后缀优先定位；一般选择仍须保持原历史顺序且不复用索引。"""
    messages = [{"role": "user", "content": value} for value in ["a", "b", "a"]]
    chosen = [{"role": "user", "content": value} for value in selected]
    selection = _history_selection(messages, chosen)
    assert selection["algorithm"] == "message_indices.v1"
    assert selection["indices"] == indices
    assert selection["message_count"] == len(messages)
    assert [messages[index] for index in indices] == chosen


@pytest.mark.parametrize("selected", [["b", "a", "b"], ["edited"]])
async def test_history_selection_rejects_reordering_or_rewriting(selected):
    """无法由单一事实历史重建的输入必须拒绝，不能用指纹掩盖正文改写。"""
    messages = [{"role": "user", "content": value} for value in ["a", "b"]]
    chosen = [{"role": "user", "content": value} for value in selected]
    with pytest.raises(LlmRequestError, match="模型输入无法对应持久历史"):
        _history_selection(messages, chosen)


async def test_history_selection_records_only_protocol_state_compatibility_drop():
    """模型切换降级可由持久索引重建，且不能放宽正文或工具字段的改写。"""
    source = {
        "role": "assistant",
        "content": "portable answer",
        "tool_calls": [{"id": "call", "name": "read", "args": {"path": "a.txt"}}],
        "protocol_state": {"provider": "old", "items": []},
    }
    selected = deepcopy(source)
    selected.pop("protocol_state")
    selection = _history_selection([source], [selected])
    assert selection["algorithm"] == "message_indices.v2"
    assert selection["indices"] == [0]
    assert selection["transformations"] == [{
        "index": 0,
        "removed_fields": ["protocol_state"],
        "reason": "model_compatibility",
    }]
    assert "protocol_state" in source
    with pytest.raises(LlmRequestError, match="模型输入无法对应持久历史"):
        _history_selection([source], [{**selected, "content": "rewritten"}])


class MemoryLog:
    """只实现公开日志接口，不依赖数据库、SQLite 或源工作区。"""

    def __init__(self, session_id="session-a"):
        self.session_id = session_id
        self.events = []
        self.actor_id = None
        self.command_context = {}

    @property
    def next_seq(self):
        return len(self.events)

    def append(self, kind, data):
        event = {
            "seq": self.next_seq, "ts": float(self.next_seq),
            "type": kind, "data": deepcopy(data),
        }
        self.events.append(event)
        return deepcopy(event)

    def read(self):
        return deepcopy(self.events)

    def close(self):
        pass


class ScriptedAdapter:
    """逐次返回确定性片段，记录实际请求以验证历史回填。"""

    def __init__(self, *attempts):
        self.attempts = list(attempts)
        self.requests = []

    async def stream(self, request):
        self.requests.append(deepcopy(request))
        chunks = self.attempts.pop(0)
        for chunk in chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


class RecordingScheduler:
    """测试图到调度器接口；调度器自身的并发及平台工具由其专属测试覆盖。"""

    def __init__(self):
        self.invocations = []

    async def execute(self, **kwargs):
        self.invocations.append(kwargs)
        messages = []
        for call in kwargs["calls"]:
            base = {
                "turn": kwargs["turn"], "step": kwargs["step"],
                "attempt_id": kwargs["attempt_id"], "call_id": call["id"], "name": call["name"],
            }
            event = kwargs["log"].append("tool/call", {**base, **call})
            status = "succeeded" if kwargs["allow_dispatch"] else "not_started"
            if "parse_error" in call:
                status = "failed"
            if status == "succeeded":
                kwargs["log"].append("tool/dispatch", {**base, "call_seq": event["seq"]})
            result = kwargs["log"].append("tool/result", {
                **base, "call_seq": event["seq"], "status": status,
                "content": "完整工具正文", "is_error": status != "succeeded",
            })
            kwargs["emit"]({
                "kind": "tool_result", "seq": result["seq"], "event_ts": result["ts"],
                "record_type": result["type"], **result["data"],
            })
            messages.append({
                "role": "tool", "tool_call_id": call["id"], "name": call["name"],
                "content": "完整工具正文", "is_error": status != "succeeded",
            })
        return messages


def request(model="model-a"):
    """为每回合固定 profile 和供应商选项。"""
    return LlmRequest(
        model=model, messages=[], system="平台系统提示", tools=[
            ToolSpec("read", "读取", {"type": "object", "properties": {}})
        ], max_tokens=123, provider="openai", reasoning_effort="off",
        protocol="anthropic_messages", profile_id="profile-a", profile_version=7,
        compatibility_key="profile-a:7", temperature=0.3,
        provider_options={"prompt_cache": False},
    )


def tool_chunks(call_id="call-a", finish="tool_calls", raw="{}"):
    """一次模型完整工具响应。"""
    return [ToolCallStart(0, call_id, "read"), ToolCallDelta(0, raw), Done(finish)]


async def make_runtime(adapter, *, settings=None, log=None, scheduler=None):
    """使用真实七节点与请求模板，注入当前会话独有的依赖。"""
    graph = await build_agent(settings or LoopSettings(), adapter=adapter,
                              scheduler=scheduler, request=request())
    return AgentRuntime(log or MemoryLog(), graph)


@pytest.mark.parametrize("effort", ["high", "off"])
async def test_runtime_template_reasoning_override_rebuilds_wire_options(monkeypatch, effort):
    """真实 Runtime 与适配器验证 medium 模板切档、请求头及回到模板默认档位。"""
    from app.llm.contracts import ModelConfig
    from app.llm.providers.openai import OpenAiAdapter
    from app.llm.resolver import resolve_request
    from tests.test_loop_llm import FakeClient, FakeStream, chat

    client = FakeClient()
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: client)
    adapter = OpenAiAdapter(api_key="unit", base_url="https://unit.invalid/v1", provider="deepseek")
    template = resolve_request(ModelConfig(
        "openai_chat", "https://unit.invalid/v1", "deepseek-chat", reasoning_effort="medium",
    ), messages=[])
    original = deepcopy(template)
    graph = await build_agent(LoopSettings(), adapter=adapter, request=template)
    runtime = AgentRuntime(MemoryLog(), graph)
    try:
        for override, expected in [(None, "medium"), (effort, effort), (None, "medium")]:
            client.stream = FakeStream([chat({"content": "答复"}, finish="stop")])
            await runtime.submit("继续", reasoning_effort=override)
            await runtime.wait()
            events = runtime.log.read()
            assert events[-1]["type"] == "turn/end"
            assert events[-1]["data"]["reason"] == "completed"
            enabled = expected != "off"
            wire = client.requests[-1]
            assert wire["extra_body"]["thinking"] == {"type": "enabled" if enabled else "disabled"}
            assert "reasoning_effort" not in wire  # 旧 DeepSeek 只支持思考开关。
            header = [e["data"]["header"] for e in events if e["type"] == "request/header"][-1]
            assert header["reasoning_effort"] == expected
            assert header["thinking"] is enabled
            assert header["reasoning_enabled"] is enabled
            assert header["provider_options"]["thinking"] == wire["extra_body"]["thinking"]
            assert header["provider_options"].get("reasoning_effort") == wire.get("reasoning_effort")
        assert len(client.requests) == 3
        assert template == original
    finally:
        await runtime.close()
        await adapter.close()


async def test_seven_nodes_tool_loop_second_turn_and_committed_publication():
    """模型—工具—再模型以及第二回合历史与持久事实完全一致。"""
    adapter = ScriptedAdapter(tool_chunks(), [TextDelta("答复"), Done("stop")],
                              [TextDelta("第二轮"), Done("stop")])
    scheduler = RecordingScheduler()
    runtime = await make_runtime(adapter, scheduler=scheduler)
    assert set(runtime._graph.nodes) - {"__start__"} == {
        "pre_step", "model", "retry_wait", "tools", "close_step", "decide_next", "finalize_turn",
    }
    observed = []

    def observe(payload):
        """实时事件必须引用已经持久提交的事实。"""
        assert runtime.log.read()[payload["seq"]]["seq"] == payload["seq"]
        observed.append(payload)

    runtime.subscribe(observe)
    await runtime.start_turn("开始")
    await runtime.wait()
    assert len(adapter.requests) == 2
    assert adapter.requests[1].messages[-1]["content"] == "完整工具正文"
    first_history = derive_messages(runtime.log.read())
    await runtime.start_turn("继续")
    await runtime.wait()
    assert adapter.requests[-1].messages == [*first_history, {"role": "user", "content": "继续"}]
    assert len(scheduler.invocations) == 1
    assert [e["reason"] for e in observed if e["kind"] == "turn_end"] == ["completed"] * 2
    assert adapter.requests[0].profile_version == 7
    messages = [event["data"] for event in runtime.log.read() if event["type"] == "assistant/message"]
    assert all(isinstance(message["latency_ms"], int) and message["latency_ms"] >= 0 for message in messages)
    await runtime.close()


@pytest.mark.parametrize("retryable,expected", [(True, 2), (False, 1)])
async def test_retry_classification_stays_in_same_step(retryable, expected):
    """仅瞬态失败重试，且不消耗额外 step 或把失败前缀当历史。"""
    adapter = ScriptedAdapter(
        [TextDelta("失败前缀"), LlmRequestError("失败", code="provider", retryable=retryable)],
        [TextDelta("成功"), Done("stop", {"completion_tokens": 2})],
    )
    runtime = await make_runtime(adapter, settings=LoopSettings(dsh_model_retry_delay_seconds=0))
    await runtime.start_turn("请求")
    await runtime.wait()
    events = runtime.log.read()
    assert len(adapter.requests) == expected
    assert len([e for e in events if e["type"] == "step/start"]) == 1
    assert len([e for e in events if e["type"] == "assistant/attempt_start"]) == expected
    assert all("失败前缀" != m["content"] for m in derive_messages(events))
    await runtime.close()


@pytest.mark.parametrize("chunks,code", [
    ([TextDelta("无终态")], "missing_finish"),
    ([Done("stop")], "empty_response"),
    ([ToolCallDelta(0, "{}"), Done("tool_calls")], "invalid_tool_call"),
    ([ProviderItemStart("p", 0, "reasoning"), Done("stop", protocol_state=ProtocolState())],
     "invalid_protocol_state"),
])
async def test_failed_attempt_never_dispatches_or_enters_history(chunks, code):
    """EOF、空回复、缺失身份和不完整协议状态都不能伪造成功。"""
    runtime = await make_runtime(ScriptedAdapter(chunks))
    await runtime.start_turn("请求")
    await runtime.wait()
    events = runtime.log.read()
    assert [e["data"]["error_code"] for e in events if e["type"] == "assistant/attempt"] == [code]
    assert not any(e["type"] == "assistant/message" for e in events)
    assert events[-1]["data"]["reason"] == "error"
    await runtime.close()


@pytest.mark.parametrize("finish,reason", [("length", "max_tokens"), ("content_filter", "error")])
async def test_terminal_model_calls_are_settled_without_dispatch(finish, reason):
    """截断和供应商终态仍配齐结果，但禁止执行工具及继续请求模型。"""
    scheduler = RecordingScheduler()
    runtime = await make_runtime(ScriptedAdapter(tool_chunks(finish=finish)), scheduler=scheduler)
    await runtime.start_turn("请求")
    await runtime.wait()
    assert scheduler.invocations[0]["allow_dispatch"] is False
    assert not any(e["type"] == "tool/dispatch" for e in runtime.log.read())
    assert derive_messages(runtime.log.read())[-1]["is_error"] is True
    assert runtime.log.read()[-1]["data"]["reason"] == reason
    await runtime.close()


async def test_max_steps_exceeds_langgraph_default_and_settles_once():
    """十六步预算不能因图默认递归上限 25 而提前失败。"""
    adapter = ScriptedAdapter(*(tool_chunks(str(i)) for i in range(16)))
    runtime = await make_runtime(adapter, scheduler=RecordingScheduler())
    await runtime.start_turn("请求")
    await runtime.wait()
    assert len(adapter.requests) == 16
    ends = [e for e in runtime.log.read() if e["type"] == "turn/end"]
    assert len(ends) == 1 and ends[0]["data"]["reason"] == "max_steps"
    await runtime.close()


async def test_protocol_state_survives_tool_roundtrip_and_runtime_restart():
    """重启后的请求继续携带完整原始状态及其工具结果。"""
    item = {"type": "reasoning", "encrypted_content": "cipher", "id": "p"}
    state = ProtocolState(provider="anthropic", protocol="anthropic_messages",
                          model="model-a", compatibility_key="profile-a:7", items=[item])
    adapter = ScriptedAdapter(
        [ProviderItemStart("p", 0, "reasoning"), ProviderItemEnd("p", item),
         *tool_chunks()[:-1], Done("tool_calls", {"prompt_tokens": 4}, state)],
        [TextDelta("完成"), Done("stop")],
    )
    runtime = await make_runtime(adapter, scheduler=RecordingScheduler())
    await runtime.start_turn("请求")
    await runtime.wait()
    assert adapter.requests[1].messages[1]["protocol_state"]["items"] == [item]
    log = runtime.log
    await runtime.close()
    resumed_adapter = ScriptedAdapter([TextDelta("继续"), Done("stop")])
    resumed = await make_runtime(resumed_adapter, log=log)
    await resumed.start_turn("新请求")
    await resumed.wait()
    assert resumed_adapter.requests[0].messages[1]["protocol_state"]["items"] == [item]
    headers = [e for e in log.read() if e["type"] == "request/header"]
    assert headers[-1]["data"]["reason"] == "resume"
    await resumed.close()


async def test_per_turn_dependencies_do_not_share_models_between_sessions():
    """共享无模型图的两个会话使用各自 adapter、profile 及请求指纹。"""
    graph = await build_agent(LoopSettings())
    a = ScriptedAdapter([TextDelta("a"), Done("stop")])
    b = ScriptedAdapter([TextDelta("b"), Done("stop")])
    ra, rb = AgentRuntime(MemoryLog("a"), graph), AgentRuntime(MemoryLog("b"), graph)
    await asyncio.gather(
        ra.start_turn("a", dependencies=TurnDependencies(a, request=request("a"))),
        rb.start_turn("b", dependencies=TurnDependencies(b, request=request("b"))),
    )
    await asyncio.gather(ra.wait(), rb.wait())
    assert a.requests[0].model == "a" and b.requests[0].model == "b"
    assert a.requests[0].messages == [{"role": "user", "content": "a"}]
    assert b.requests[0].messages == [{"role": "user", "content": "b"}]
    await asyncio.gather(ra.close(), rb.close())


async def test_immediate_cancel_keeps_source_interface_and_single_terminal():
    """协程未获得首个时间片时取消，也必须补齐唯一回合终态。"""
    runtime = await make_runtime(ScriptedAdapter())
    await runtime.start_turn("请求")
    assert await runtime.cancel()
    assert await runtime.cancel()
    await runtime.wait()
    assert not runtime.running
    assert [e["data"]["reason"] for e in runtime.log.read()
            if e["type"] == "turn/end"] == ["cancelled"]
    assert len([e for e in runtime.log.read() if e["type"] == "runtime/cancel_requested"]) == 1
    await runtime.close()
    with pytest.raises(RuntimeClosedError):
        await runtime.start_turn("关闭后")


async def test_stream_cancel_preserves_only_safe_text_and_closes_adapter():
    """取消保存已显示正文，丢弃未完成工具及 opaque 状态，并关闭异步流。"""
    entered, closed = asyncio.Event(), asyncio.Event()

    class WaitingAdapter:
        """在片段间可取消的真实异步生成器。"""

        async def stream(self, request):
            try:
                yield TextDelta("安全前缀")
                yield ReasoningDelta("思考")
                yield ToolCallStart(0, "partial", "read")
                yield ProviderItemStart("p", 0, "reasoning")
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

    runtime = await make_runtime(WaitingAdapter())
    await runtime.start_turn("请求")
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(TurnAlreadyRunningError):
        await runtime.start_turn("并发输入")
    with pytest.raises(TurnAlreadyRunningError):
        await runtime.replace_graph(runtime._graph)
    assert await runtime.cancel()
    await runtime.wait()
    assert closed.is_set()
    message = derive_messages(runtime.log.read())[-1]
    assert message == {"role": "assistant", "content": "安全前缀", "reasoning_content": "思考"}
    await runtime.replace_graph(runtime._graph)
    await runtime.close()


class AtomicLog(MemoryLog):
    """模拟只允许持有者原子接受输入的持久日志。"""

    def __init__(self):
        super().__init__()
        self.atomic_calls = []

    def begin_turn(self, data, *, writer_id=None):
        self.atomic_calls.append((deepcopy(data), writer_id, self.actor_id,
                                  deepcopy(self.command_context)))
        if writer_id != "owner":
            raise RuntimeError("writer lease required")
        if data.get("client_message_id"):
            for event in self.read():
                if event["type"] == "user/message" and event["data"].get(
                    "client_message_id"
                ) == data["client_message_id"]:
                    started = next(e for e in self.read() if e["type"] == "turn/start"
                                   and e["data"]["turn"] == event["data"]["turn"])
                    return started, event
        turn = 1 + sum(e["type"] == "turn/start" for e in self.events)
        return (self.append("turn/start", {"turn": turn}),
                self.append("user/message", {**data, "turn": turn}))


async def test_submit_uses_atomic_log_identity_and_idempotent_receipt():
    """身份与命令上下文透传给原子 begin_turn，重复完成输入不再调用模型。"""
    adapter = ScriptedAdapter([TextDelta("好"), Done("stop")])
    graph = await build_agent(LoopSettings(), adapter=adapter, request=request())
    log = AtomicLog()
    runtime = AgentRuntime(log, graph, writer_id="owner", actor_id="actor")
    assert await runtime.submit("请求", client_message_id="msg1",
                                command_context={"request_id": "req1"}) == 1
    await runtime.wait()
    assert await runtime.submit("请求", client_message_id="msg1") == 1
    assert len(adapter.requests) == 1
    assert log.atomic_calls[0][1:] == ("owner", "actor", {"request_id": "req1"})
    assert log.atomic_calls[0][0]["client_message_id"] == "msg1"
    await runtime.close()


async def test_persistent_log_requires_explicit_owned_recovery():
    """持久日志的开放回合不由 start_turn 自动抢占或结算。"""
    log = AtomicLog()
    log.append("turn/start", {"turn": 8})
    runtime = await make_runtime(ScriptedAdapter(), log=log)
    before = log.read()
    with pytest.raises(RuntimeError, match="explicit owned recovery"):
        await runtime.submit("请求")
    assert log.read() == before
    assert log.atomic_calls == []
    # 主 service 确认租约后才会调用公开 recover；这里模拟该授权边界之后的调用。
    await runtime.recover()
    assert log.read()[-1]["data"]["reason"] == "interrupted"
    await runtime.close()


async def test_truncated_provider_items_still_settle_declared_tool_calls():
    """截断的 opaque 块不回传，但已声明调用仍按源语义配齐未启动结果。"""
    scheduler = RecordingScheduler()
    adapter = ScriptedAdapter([
        ProviderItemStart("p", 0, "function_call"),
        ToolCallStart(0, "a", "read"), ToolCallDelta(0, "{}"), Done("max_tokens"),
    ])
    runtime = await make_runtime(adapter, scheduler=scheduler)
    await runtime.start_turn("请求")
    await runtime.wait()
    assert scheduler.invocations[0]["allow_dispatch"] is False
    assert runtime.log.read()[-1]["data"]["reason"] == "max_tokens"
    assert derive_messages(runtime.log.read())[-1]["is_error"]
    assert "protocol_state" not in derive_messages(runtime.log.read())[-2]
    await runtime.close()


async def test_cancel_during_retry_wait_does_not_issue_another_request():
    """退避等待可立即取消，不发起第二次 SDK 请求。"""
    adapter = ScriptedAdapter(
        [LlmRequestError("暂时失败", code="transport", retryable=True)],
        [TextDelta("不应发起"), Done("stop")],
    )
    runtime = await make_runtime(
        adapter, settings=LoopSettings(dsh_model_retry_delay_seconds=30)
    )
    entered = asyncio.Event()
    runtime.subscribe(lambda payload: entered.set() if payload["kind"] == "retry_wait" else None)
    await runtime.start_turn("请求")
    await asyncio.wait_for(entered.wait(), 2)
    await runtime.cancel()
    await asyncio.wait_for(runtime.wait(), 2)
    assert len(adapter.requests) == 1
    assert runtime.log.read()[-1]["data"]["reason"] == "cancelled"
    await runtime.close()


async def test_attempt_error_closes_stream_and_does_not_expose_unclassified_exception():
    """消费者校验失败仍关闭生成器，未知异常原文不流入事实和浏览器。"""
    closed = asyncio.Event()

    class BadAdapter:
        async def stream(self, request):
            try:
                yield TextDelta("前缀")
                yield Done("stop")
                yield TextDelta("late")
            finally:
                closed.set()

    runtime = await make_runtime(BadAdapter())
    await runtime.start_turn("请求")
    await runtime.wait()
    assert closed.is_set()
    failure = next(e for e in runtime.log.read() if e["type"] == "assistant/attempt")
    assert failure["data"]["error"] == "模型请求失败"
    assert len(derive_messages(runtime.log.read())) == 1
    await runtime.close()


async def test_recovery_publishes_known_queued_success_and_resumes_without_enqueue():
    """恢复已知入队任务时发布成功 tool 结果，后续只调用模型不重放入队。"""
    from tests.test_loop_runtime_recovery import open_history

    log = MemoryLog()
    for event in open_history():
        log.append(event["type"], event["data"])
    log.append("task/queued", {
        "turn": 1, "attempt_id": "attempt", "call_id": "b",
        "task_id": "task-123", "content": "已入队 task-123",
    })
    adapter = ScriptedAdapter([TextDelta("任务已提交"), Done("stop")])
    runtime = await make_runtime(adapter, log=log)
    observed = []
    runtime.subscribe(observed.append)
    await runtime.recover()
    published = next(p for p in observed if p["kind"] == "tool_result" and p["call_id"] == "b")
    assert published["status"] == "succeeded" and published["is_error"] is False
    assert published["task_id"] == "task-123"
    await runtime.submit("继续")
    await runtime.wait()
    assert len(adapter.requests) == 1
    assert adapter.requests[0].messages[-2]["content"] == "已入队 task-123"
    assert sum(e["type"] == "task/queued" for e in log.read()) == 1
    await runtime.close()


async def test_cancel_reuses_service_cancel_fact_and_preserves_caller_owned_log():
    """命令层已记录取消时不重复写入，关闭 Runtime 不关闭外部日志。"""
    class OwnedLog(MemoryLog):
        def close(self):
            raise AssertionError("runtime must not close caller log")

    runtime = await make_runtime(ScriptedAdapter(), log=OwnedLog())
    await runtime.start_turn("请求")
    runtime.log.append("runtime/cancel_requested", {"turn": runtime.active_turn})
    await runtime.cancel()
    await runtime.wait()
    assert sum(e["type"] == "runtime/cancel_requested" for e in runtime.log.read()) == 1
    await runtime.close()
