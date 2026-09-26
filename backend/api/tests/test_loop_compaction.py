"""会话摘要的真实请求预算、持久回放、失败与取消边界。"""

import asyncio
import json
from copy import deepcopy

import pytest

from app.agent.compaction import MAX_COMPACTION_CALLS, SUMMARY_BOUNDARY, ContextCompactor
from app.agent.events import project_fact, trace_frame
from app.agent.loop import TurnDependencies, _history_selection, build_agent
from app.agent.loop_presentation import request_summary
from app.agent.loop_settings import LoopSettings
from app.agent.loop_wiring import _prompt_tokens
from app.agent.model_budget import BudgetedAdapter, ModelCallBudget
from app.agent.runtime import AgentRuntime
from app.errors import AppError, ErrorCode
from app.harness.contracts.loop_events import EVENT_SCHEMAS
from app.harness.memory.agent_messages import derive_messages
from app.llm.contracts import ModelConfig, SystemSegment
from app.llm.loop_contracts import Done, LlmRequestError, TextDelta, ToolCallDelta, ToolCallStart
from app.llm.providers.common import validate_messages
from app.llm.resolver import AuthorizedProfileSnapshot, resolve_request
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter


def request_factory(protocol="openai_chat"):
    """使用真实协议转换，较长平台提示让摘要请求与主请求预算独立可测。"""
    model = "claude-sonnet-4-5" if protocol == "anthropic_messages" else "gpt-4o"
    profile = AuthorizedProfileSnapshot(ModelConfig(
        protocol=protocol, base_url="https://example.test/v1", model=model,
        api_key="test-only", max_tokens=256, reasoning_enabled=False,
    ))

    def build(messages, summary):
        """模拟生产中核心提示及非缓存摘要段，不创建任何网络连接。"""
        segments = (SystemSegment("平台规则：遵守原始用户要求。" * 100),)
        if summary:
            segments += (SystemSegment(SUMMARY_BOUNDARY + summary, cacheable=False),)
        return resolve_request(profile, messages=messages, system_segments=segments)

    return build


def conversation():
    """较早约束和大量观察应可摘要，最新用户要求保持原文。"""
    return [{"role": "user", "content": "预算不超过100元，只修改目标文件。"},
            {"role": "assistant", "content": "verified evidence " * 360},
            {"role": "user", "content": "继续，仍然遵守之前的限制"}]


def capacity(build, messages, *, overflow=False):
    """按实际 wire 成本选择接近阈值或超过硬预算的容量，避免字符数碰运气。"""
    request = build(messages, "")
    budget = int(_prompt_tokens(request) * (.95 if overflow else 1.05))
    return budget + request.max_tokens + 256


def compactor(log, adapter, build, messages, *, overflow=False):
    """构建同源估算的回合摘要器。"""
    store_messages(log, messages)
    return ContextCompactor(log, adapter, build, _prompt_tokens, capacity(build, messages, overflow=overflow))


def store_messages(log, messages):
    """测试也先提交原始事实，不能用只驻内存的历史冒充已保存来源。"""
    for message in messages[len(derive_messages(log.read())):]:
        if message["role"] == "user":
            log.append("user/message", {"content": message["content"]})
        elif message["role"] == "assistant":
            log.append("assistant/message", {"message": message})
        else:
            log.append("tool/result", {"call_id": message["tool_call_id"], "name": message["name"],
                                       "content": message["content"], "status": "succeeded"})


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
async def test_compacts_and_rebuilds_same_input_after_restart(protocol):
    """成功摘要只覆盖旧前缀，新句柄恢复相同请求；三种协议的消息配对不变。"""
    messages, log, build = conversation(), MemoryLog(), request_factory(protocol)
    original = deepcopy(messages)
    adapter = ScriptedAdapter([TextDelta("约束：预算100元；只修改目标文件。已核实来源，待继续。"),
                               Done("stop", usage={"prompt_tokens": 100, "completion_tokens": 20})])
    compact = compactor(log, adapter, build, messages)
    assert compact.preflight(messages).messages == messages
    assert adapter.requests == []
    result = await compact.prepare(messages)
    assert result.messages == messages[-1:]
    assert "预算100元" in result.system
    assert messages == original
    saved = log.read()[-1]
    assert saved["type"] == "context/compacted"
    assert saved["data"]["covered_messages"] == 2
    assert saved["data"]["usage"]["completion_tokens"] == 20
    assert adapter.requests[0].tools == [] and adapter.requests[0].tool_choice == "none"
    restarted = ContextCompactor(log, ScriptedAdapter(), build, _prompt_tokens, compact.context_window)
    assert await restarted.prepare(messages) == result
    selection = _history_selection(messages, result.messages)
    assert [messages[i] for i in selection["indices"]] == result.messages
    meter = request_summary(result, context_window=compact.context_window)["context_meter"]
    assert meter["compacted"] and meter["breakdown"]["memory_files"] > 0
    assert sum(meter["breakdown"].values()) == meter["input_tokens"]


@pytest.mark.asyncio
async def test_same_turn_preserves_latest_user_and_parallel_tool_group():
    """同轮工具链仅压缩已闭合单元，最新用户输入、opaque和并行配对逐字保留。"""
    messages = [conversation()[0],
                {"role": "assistant", "content": "", "tool_calls": [{"id": "old", "name": "read", "args": {}}]},
                {"role": "tool", "tool_call_id": "old", "name": "read", "content": "observations " * 500},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "a", "name": "read", "args": {}}, {"id": "b", "name": "read", "args": {}}]},
                {"role": "tool", "tool_call_id": "a", "name": "read", "content": "A"},
                {"role": "tool", "tool_call_id": "b", "name": "read", "content": "B"}]
    log, build = MemoryLog(), request_factory()
    adapter = ScriptedAdapter([TextDelta("旧读取完成，预算限制仍有效。"), Done("stop")])
    result = await compactor(log, adapter, build, messages).prepare(messages)
    assert result.messages == [messages[0], *messages[3:]]
    validate_messages(result.messages)
    assert _history_selection(messages, result.messages)["indices"] == [0, 3, 4, 5]


@pytest.mark.asyncio
async def test_incremental_summary_uses_previous_summary_without_old_raw_text():
    """二次压缩只读新增前缀并合并已有摘要，不重复消费已压缩旧正文。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    adapter = ScriptedAdapter([TextDelta("第一份记忆：保留预算100元。"), Done("stop")],
                              [TextDelta("第二份记忆：预算100元，新增事实已核实。"), Done("stop")])
    compact = compactor(log, adapter, build, messages)
    await compact.prepare(messages)
    messages.extend([{"role": "assistant", "content": "new evidence " * 650},
                     {"role": "user", "content": "继续处理剩余事项"}])
    store_messages(log, messages)
    result = await compact.prepare(messages)
    payload = json.loads(adapter.requests[1].messages[0]["content"])
    assert "第一份记忆" in payload["previous_summary"]
    assert "verified evidence" not in json.dumps(payload)
    assert result.messages == messages[-1:]
    saved = [event for event in log.read() if event["type"] == "context/compacted"]
    assert saved[1]["data"]["previous_summary_seq"] == saved[0]["seq"]
    assert saved[1]["data"]["covered_messages"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [
    [TextDelta("unfinished")], [TextDelta("truncated"), Done("length")], [Done("stop")],
    [ToolCallStart(0, "call", "read"), ToolCallDelta(0, "{}"), Done("tool_calls")],
    [RuntimeError("PRIVATE upstream credential")],
])
async def test_invalid_summary_preserves_original_and_does_not_retry(chunks):
    """摘要异常/截断/空输出/工具调用都不推进边界，原文可容纳时继续原请求。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    adapter = ScriptedAdapter(chunks)
    compact = compactor(log, adapter, build, messages)
    result = await compact.prepare(messages)
    assert result.messages == messages
    assert await compact.prepare(messages) == result
    assert len(adapter.requests) == 1
    assert not any(event["type"] == "context/compacted" for event in log.read())
    assert "PRIVATE" not in json.dumps(log.read())


@pytest.mark.asyncio
async def test_failed_summary_over_hard_budget_is_explicit_and_original_stays():
    """原文已超限时不得静默删历史；返回标准预算错误且不提交假摘要。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    compact = compactor(log, ScriptedAdapter([Done("length")]), build, messages, overflow=True)
    with pytest.raises(AppError) as error:
        await compact.prepare(messages)
    assert error.value.code == ErrorCode.BUDGET_EXCEEDED
    assert all(event["type"] != "context/compacted" for event in log.read())


@pytest.mark.asyncio
async def test_cancellation_closes_summary_stream_and_budget_slot():
    """摘要运行在主回合取消域，取消时释放流与并发，不持久化半成品。"""
    entered, closed = asyncio.Event(), asyncio.Event()

    class WaitingAdapter:
        """可取消的确定性供应商替身。"""

        async def stream(self, request):
            """输出前缀后等待取消，并记录生成器释放。"""
            try:
                yield TextDelta("未完成摘要")
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

    budget = ModelCallBudget(max_calls=2, max_concurrent=1, max_calls_per_run=2)
    adapter = BudgetedAdapter(WaitingAdapter(), budget, "root")
    messages, log, build = conversation(), MemoryLog(), request_factory()
    pending = asyncio.create_task(compactor(log, adapter, build, messages).prepare(messages))
    await asyncio.wait_for(entered.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert closed.is_set() and budget.snapshot()["active"] == 0
    assert budget.snapshot()["calls"] == 1
    assert all(event["type"] != "context/compacted" for event in log.read())
    # 取消后连主回答预留也必须释放，其他专家可以使用尚未消费的最后一次额度。
    other = BudgetedAdapter(ScriptedAdapter([TextDelta("完成"), Done("stop")]), budget, "expert")
    async for _ in other.stream(build([{"role": "user", "content": "继续"}], "")):
        pass
    assert budget.snapshot()["calls"] == 2


@pytest.mark.asyncio
async def test_real_graph_replay_and_call_budget_include_summary():
    """真实图先摘要再回答，两个请求计费；事实索引能精确重建回答输入。"""
    log, build, messages = MemoryLog(), request_factory(), conversation()
    log.append("user/message", {"content": messages[0]["content"]})
    log.append("assistant/message", {"message": messages[1]})
    provider = ScriptedAdapter([TextDelta("记忆：预算100元。"), Done("stop")],
                               [TextDelta("继续处理剩余工作。"), Done("stop")])
    budget = ModelCallBudget(max_calls=4, max_concurrent=1, max_calls_per_run=4)
    adapter = BudgetedAdapter(provider, budget, "root")
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, capacity(build, messages))

    async def prepare(history, effort):
        """真实图支持异步上下文准备。"""
        return await compact.prepare(history)

    graph = await build_agent(LoopSettings(dsh_max_steps=4))
    runtime = AgentRuntime(log, graph)
    await runtime.submit(messages[-1]["content"], dependencies=TurnDependencies(
        adapter, request_factory=prepare, context_window=compact.context_window,
    ))
    await runtime.wait()
    assert len(provider.requests) == budget.snapshot()["calls"] == 2
    assert derive_messages(log.read())[:3] == messages
    events = log.read()
    start = next(e for e in events if e["type"] == "assistant/attempt_start")
    data = start["data"]
    source = derive_messages(e for e in events if e["seq"] <= data["history_upto_seq"])
    replay = [source[i] for i in data["history_selection"]["indices"]]
    assert replay == provider.requests[1].messages
    header = next(e for e in events if e["seq"] == data["header_seq"])
    assert header["data"]["header"] == provider.requests[1].header()
    assert events[-1]["type"] == "turn/end" and events[-1]["data"]["reason"] == "completed"


def test_summary_projection_never_exposes_private_text():
    """普通流和诊断流均只给元信息，不能绕过摘要正文保密边界。"""
    event = {"type": "context/compacted", "seq": 4, "ts": 1., "session_id": "s", "data": {
        "summary": "PRIVATE historical context", "reason": "summary", "covered_messages": 2,
        "dropped": 2, "kept": 1, "in_scope_total": 3, "limit": 5000,
    }}
    assert project_fact(event)[0]["type"] == "context.trimmed"
    assert "PRIVATE" not in json.dumps(project_fact(event))
    assert "PRIVATE" not in json.dumps(trace_frame(event, "s", source="history"))


@pytest.mark.asyncio
async def test_small_context_and_uncompressible_latest_group():
    """普通短对话不增加摘要调用；最新唯一工具组超限时不能拆散或抛弃。"""
    log, build, adapter = MemoryLog(), request_factory(), ScriptedAdapter()
    messages = [{"role": "user", "content": "你好"}]
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, 8000)
    assert (await compact.prepare(messages)).messages == messages
    assert adapter.requests == []
    messages.extend([{"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "name": "read", "args": {}}]},
        {"role": "tool", "tool_call_id": "c", "name": "read", "content": "huge " * 15000}])
    with pytest.raises(AppError, match="最近完整工具组"):
        compact.preflight(messages)
    assert adapter.requests == []


def test_changed_source_is_rejected_and_open_tools_are_not_compacted():
    """来源发生变化或工具组尚未闭合时不允许消费摘要。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    log.append("context/compacted", {"version": 1, "summary": "摘要", "covered_messages": 2,
                                     "source_fingerprint": "bad"})
    compact = compactor(log, ScriptedAdapter(), build, messages)
    with pytest.raises(AppError, match="不一致"):
        compact.preflight(messages)
    open_messages = [{"role": "user", "content": "读取文件"},
                     {"role": "assistant", "content": "", "tool_calls": [
                         {"id": "pending", "name": "read", "args": {}}]}]
    fresh = ContextCompactor(MemoryLog(), ScriptedAdapter(), build, _prompt_tokens, 8000)
    with pytest.raises(LlmRequestError, match="工具结果"):
        fresh.preflight(open_messages)


@pytest.mark.asyncio
async def test_compacted_image_uses_durable_source_after_next_turn():
    """图片工具只驻当前图的内容不能使持久摘要在下一轮指纹失配。"""
    messages = [conversation()[0],
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "image", "name": "read_image", "args": {"file_path": "a.png"}}]},
                {"role": "tool", "tool_call_id": "image", "name": "read_image", "content": "已读取图片 a.png"},
                {"role": "assistant", "content": "observations " * 800},
                {"role": "user", "content": "继续"}]
    log, build = MemoryLog(), request_factory()
    store_messages(log, messages)
    live = deepcopy(messages)
    live[2]["content"] = [{"type": "text", "text": "已读取图片 a.png"},
                          {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    adapter = ScriptedAdapter([TextDelta("已读取 a.png；仍需遵守预算。"), Done("stop")])
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, capacity(build, messages))
    result = await compact.prepare(live)
    assert "base64" not in adapter.requests[0].messages[0]["content"]
    assert "已读取图片 a.png" in adapter.requests[0].messages[0]["content"]
    restored = ContextCompactor(log, ScriptedAdapter(), build, _prompt_tokens, compact.context_window)
    assert await restored.prepare(derive_messages(log.read())) == result


@pytest.mark.asyncio
async def test_proactive_summary_leaves_last_call_for_answer():
    """共享预算只剩一次时跳过主动压缩，让原文仍能完成回答。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    provider = ScriptedAdapter([TextDelta("正常回答"), Done("stop")])
    budget = ModelCallBudget(max_calls=1, max_concurrent=1, max_calls_per_run=1)
    adapter = BudgetedAdapter(provider, budget, "root")
    compact = compactor(log, adapter, build, messages)
    result = await compact.prepare(messages)
    assert result.messages == messages and provider.requests == []
    assert budget.snapshot()["calls"] == 0
    async for _ in adapter.stream(result):
        pass
    assert budget.snapshot()["calls"] == 1


@pytest.mark.asyncio
async def test_reserved_answer_cannot_be_spent_by_parallel_expert():
    """摘要等待网络时，其他专家不能花掉当前运行预留的主回答额度。"""
    entered, resume = asyncio.Event(), asyncio.Event()

    class SummaryAdapter:
        """允许测试在摘要网络请求中间插入其他专家调用。"""

        async def stream(self, request):
            """显式等待测试放行，不依赖时序 sleep。"""
            entered.set()
            await resume.wait()
            yield TextDelta("预算100元，等待继续。")
            yield Done("stop")

    messages, log, build = conversation(), MemoryLog(), request_factory()
    budget = ModelCallBudget(max_calls=2, max_concurrent=2, max_calls_per_run=2)
    summary_adapter = BudgetedAdapter(SummaryAdapter(), budget, "root")
    compact = compactor(log, summary_adapter, build, messages)
    pending = asyncio.create_task(compact.prepare(messages))
    await asyncio.wait_for(entered.wait(), 2)
    competitor = ScriptedAdapter()
    with pytest.raises(LlmRequestError):
        async for _ in BudgetedAdapter(competitor, budget, "expert").stream(build(messages, "")):
            pass
    assert competitor.requests == []
    resume.set()
    result = await pending
    answer = ScriptedAdapter([TextDelta("主回答"), Done("stop")])
    async for _ in BudgetedAdapter(answer, budget, "root").stream(result):
        pass
    assert budget.snapshot()["calls"] == 2 and len(answer.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["upstream", "timeout"])
async def test_failed_summary_preserves_reserved_answer_against_queued_expert(monkeypatch, failure):
    """摘要异常或内部超时回退原文时，排队专家不能抢走正式回答额度。"""
    entered, resume, expert_queued, closed = (asyncio.Event() for _ in range(4))
    original_timeout, summary_timeouts = asyncio.timeout, []

    def capture_timeout(delay):
        """保留真实超时上下文，由事件同步后重设截止时间触发取消。"""
        timeout = original_timeout(delay)
        summary_timeouts.append(timeout)
        return timeout

    monkeypatch.setattr("app.agent.compaction.asyncio.timeout", capture_timeout)

    class Provider:
        """首次摘要受控失败，后续正式回答可正常完成。"""

        def __init__(self):
            """记录实际派发请求，区分摘要和正式回答。"""
            self.requests = []

        async def stream(self, request):
            """通过事件等待故障注入，确保专家已在唯一槽位后排队。"""
            self.requests.append(request)
            if len(self.requests) == 1:
                entered.set()
                try:
                    await resume.wait()
                    raise LlmRequestError("摘要服务暂不可用", code="upstream", public_code="UPSTREAM")
                finally:
                    closed.set()
            yield TextDelta("主回答")
            yield Done("stop")

    messages, log, build = conversation(), MemoryLog(), request_factory()
    budget = ModelCallBudget(max_calls=2, max_concurrent=1, max_calls_per_run=2)
    provider = Provider()
    adapter = BudgetedAdapter(provider, budget, "root")
    compact = compactor(log, adapter, build, messages)
    competitor = ScriptedAdapter([TextDelta("专家回答"), Done("stop")])

    async def answer():
        """摘要失败后立即使用原文发起同一运行的正式回答。"""
        request = await compact.prepare(messages)
        assert request.messages == messages
        return "".join([chunk.text async for chunk in adapter.stream(request) if isinstance(chunk, TextDelta)])

    async def expert():
        """置位后直达被摘要占用的信号量，无其他等待点。"""
        expert_queued.set()
        async for _ in BudgetedAdapter(competitor, budget, "expert").stream(build(messages, "")):
            pass

    pending = [asyncio.create_task(answer())]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending.append(asyncio.create_task(expert()))
        await asyncio.wait_for(expert_queued.wait(), 2)
        if failure == "timeout":
            summary_timeouts[0].reschedule(asyncio.get_running_loop().time())
        else:
            resume.set()
        answer_result, expert_result = await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True), 2,
        )
        assert answer_result == "主回答"
        assert isinstance(expert_result, LlmRequestError)
        assert expert_result.code == "collaboration_call_budget"
        assert competitor.requests == [] and len(provider.requests) == 2
        assert closed.is_set()
        assert budget.snapshot() == {"calls": 2, "active": 0, "by_run": {"root": 2}}
        assert any(event["type"] == "context/compaction_failed" for event in log.read())
        assert all(event["type"] != "context/compacted" for event in log.read())
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await compact.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow", [False, True])
async def test_failed_summary_releases_unused_answer_on_close_or_termination(overflow):
    """回退后关闭或原文超限终止时，未消费的回答预留必须归还其他运行。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    budget = ModelCallBudget(max_calls=2, max_concurrent=1, max_calls_per_run=2)
    provider = ScriptedAdapter([LlmRequestError("摘要服务暂不可用", code="upstream", public_code="UPSTREAM")])
    compact = compactor(log, BudgetedAdapter(provider, budget, "root"), build,
                        messages, overflow=overflow)
    if overflow:
        with pytest.raises(AppError) as error:
            await compact.prepare(messages)
        assert error.value.code == ErrorCode.BUDGET_EXCEEDED
    else:
        assert (await compact.prepare(messages)).messages == messages
        await compact.aclose()
    competitor = ScriptedAdapter([TextDelta("专家回答"), Done("stop")])
    async for _ in BudgetedAdapter(competitor, budget, "expert").stream(build(messages, "")):
        pass
    assert len(competitor.requests) == 1
    assert budget.snapshot() == {"calls": 2, "active": 0, "by_run": {"root": 1, "expert": 1}}


@pytest.mark.asyncio
async def test_compaction_call_limit_stops_without_discarding_history():
    """连续扩大的单轮历史最多触发三次摘要，之后硬超限明确结束。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    provider = ScriptedAdapter(*[
        [TextDelta(f"第{i}份记忆：预算100元。"), Done("stop")]
        for i in range(MAX_COMPACTION_CALLS)
    ])
    compact = compactor(log, provider, build, messages)
    for index in range(MAX_COMPACTION_CALLS):
        if index:
            messages.extend([{"role": "assistant", "content": "new observations " * 450},
                             {"role": "user", "content": f"继续{index}"}])
            store_messages(log, messages)
        await compact.prepare(messages)
    messages.extend([{"role": "assistant", "content": "new observations " * 1100},
                     {"role": "user", "content": "继续最后事项"}])
    store_messages(log, messages)
    with pytest.raises(AppError) as error:
        await compact.prepare(messages)
    assert error.value.code == ErrorCode.BUDGET_EXCEEDED
    assert len(provider.requests) == MAX_COMPACTION_CALLS
    assert derive_messages(log.read()) == messages


@pytest.mark.asyncio
async def test_preparation_budget_error_is_public_and_schema_valid():
    """尚未发起正式模型请求的预算失败也有标准错误与唯一回合终态。"""
    from jsonschema import Draft202012Validator

    async def fail(history, effort):
        """模拟摘要后仍不能容纳的输入。"""
        raise AppError(ErrorCode.BUDGET_EXCEEDED, "上下文压缩未能满足模型预算")

    log = MemoryLog()
    graph = await build_agent(LoopSettings(dsh_max_steps=4))
    runtime = AgentRuntime(log, graph)
    await runtime.submit("继续", dependencies=TurnDependencies(ScriptedAdapter(), request_factory=fail))
    await runtime.wait()
    events = log.read()
    failure = next(event for event in events if event["type"] == "runtime/error")
    Draft202012Validator(EVENT_SCHEMAS["runtime/error"]["schema"]).validate(failure["data"])
    public = project_fact({**failure, "session_id": "session-a"})[0]
    assert public["data"]["code"] == "BUDGET_EXCEEDED"
    assert len([event for event in events if event["type"] == "turn/end"]) == 1
    assert events[-1]["data"]["reason"] == "error"
