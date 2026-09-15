"""P0 实验：真实 AgentLoop 的上下文隔离、审批归属、取消顺序与共享额度。"""

import asyncio

import pytest

from app.agent.collaboration_scope import TurnChildren
from app.agent.loop import TurnDependencies, build_agent
from app.agent.loop_settings import LoopSettings
from app.agent.model_budget import BudgetedAdapter, ModelCallBudget
from app.agent.runtime import AgentRuntime, RuntimeRegistry
from app.harness.contracts.fact_log import execution_key
from app.harness.execution.approval import ApprovalBroker, request_approval
from app.harness.execution.scheduler import ToolScheduler
from app.llm.loop_contracts import Done, LlmRequestError, TextDelta
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter, request
from tests.test_loop_runtime_tools import calls

pytestmark = pytest.mark.asyncio


class RunLog(MemoryLog):
    """仅供隔离实验的日志替身；生产持久 SubagentLog 尚待 P1 实现。"""

    def __init__(self, run_id, session_id="parent-session"):
        """共享授权会话，但每个运行有独立事实集合和序号。"""
        super().__init__(session_id)
        self.run_id = run_id


class BarrierAdapter:
    """以事件屏障证明两个模型流确实重叠运行，不依赖 sleep 计时猜测。"""

    def __init__(self, answer):
        """记录独立请求、启动与放行信号。"""
        self.answer = answer
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.requests = []

    async def stream(self, model_request):
        """被取消也须完成资源释放，供终态排序断言。"""
        self.requests.append(model_request)
        self.started.set()
        try:
            await self.release.wait()
            yield TextDelta(self.answer)
            yield Done("stop")
        finally:
            self.closed.set()


def terminal(log):
    """取回合终态，避免只检查运行标志而漏掉重复终态。"""
    return [event["data"]["reason"] for event in log.read() if event["type"] == "turn/end"]


async def test_parallel_runs_share_graph_but_not_history_registry_or_events():
    """同一图、同一授权会话的专家真正并发，主历史没有被拼进任何子请求。"""
    graph = await build_agent(LoopSettings())
    registry = RuntimeRegistry(graph)
    parent_log = MemoryLog("parent-session")
    parent_log.append("user/message", {"turn": 1, "content": "private parent history"})
    logs = [RunLog("a"), RunLog("b")]
    adapters = [BarrierAdapter("answer a"), BarrierAdapter("answer b")]
    root = await registry.get(parent_log)
    runs = [await registry.get(log) for log in logs]
    events = [[], []]
    for runtime, sink in zip(runs, events, strict=True):
        runtime.subscribe(sink.append)
    try:
        assert len({id(root), *(id(run) for run in runs)}) == 3
        assert await registry.get(logs[0]) is runs[0]
        for index, runtime in enumerate(runs):
            await runtime.submit(f"goal {index}", dependencies=TurnDependencies(
                adapter=adapters[index], request=request(),
            ))
        await asyncio.wait_for(asyncio.gather(*(adapter.started.wait() for adapter in adapters)), 3)
        assert all(run.running for run in runs)
        for adapter in adapters:
            adapter.release.set()
        await asyncio.gather(*(run.wait() for run in runs))
        for index, log in enumerate(logs):
            assert terminal(log) == ["completed"]
            assert [e["seq"] for e in log.read()] == list(range(len(log.read())))
            assert adapters[index].requests[0].messages == [{"role": "user", "content": f"goal {index}"}]
            assert all(event["run_id"] == log.run_id for event in events[index])
            assert all(event["session_id"] == "parent-session" for event in events[index])
        assert len(parent_log.read()) == 1
    finally:
        await registry.close()


async def test_child_approval_keeps_authorization_session_and_cannot_clear_root_gate():
    """相同调用 ID 的专家审批路由隔离，关闭专家保留主 Agent 和其他专家授权。"""
    graph = await build_agent(LoopSettings())
    broker = ApprovalBroker()
    logs = [MemoryLog("parent-session"), RunLog("a"), RunLog("b")]
    runtimes = [AgentRuntime(log, graph, approval_broker=broker) for log in logs]
    cards = [[], [], []]

    def make_gate(index):
        """为每个运行绑定可识别的审批通道。"""
        async def gate(card):
            """记录真实审批身份后返回当前运行的决定。"""
            cards[index].append(card)
            return "always"
        return gate

    try:
        for index, runtime in enumerate(runtimes):
            runtime.set_approval_gate(make_gate(index))
            await request_approval(
                session_id=runtime.session_id, execution_id=runtime.execution_id,
                log=runtime.log, turn=1, step=1, attempt_id="same-attempt",
                call={"id": "same-call", "name": "edit", "args": {}},
                emit=lambda event: None, approval_broker=broker,
            )
        assert len({values[0]["approval_id"] for values in cards}) == 3
        assert all(values[0]["session_id"] == "parent-session" for values in cards)
        await runtimes[1].close()
        assert broker.gate_for(runtimes[1].execution_id) is None
        for index in (0, 2):
            assert broker.gate_for(runtimes[index].execution_id) is not None
            assert broker.is_always_allowed(runtimes[index].execution_id, "edit")
    finally:
        await asyncio.gather(*(runtime.close() for runtime in runtimes))


async def test_real_scheduler_binds_child_run_and_routes_approval_without_changing_acl_session():
    """走真实模型—工具—模型链，验证 Scheduler 将运行身份交给工具与审批两端。"""
    identities, cards = [], []

    class BoundTool:
        """测试工具只返回绑定身份，不访问工作区或绕过生产工具门禁。"""

        name = "read"
        description = "测试身份绑定"
        schema = {"type": "object", "properties": {}}
        metadata = {"dsh_access": "read", "dsh_requires_approval": True}

        def bind_call(self, identity):
            """捕获真实调度器传入的授权与运行标识。"""
            identities.append(identity)
            return self

        async def ainvoke(self, arguments):
            """审批通过后返回固定正文供真实图回填。"""
            return "tool evidence"

    async def approve(card):
        """只有子运行的审批通道应该收到该卡。"""
        cards.append(card)
        return "allow"

    broker, settings = ApprovalBroker(), LoopSettings()
    scheduler = ToolScheduler(settings, [BoundTool()], approval_broker=broker)
    source = ScriptedAdapter(calls("read"), [TextDelta("result"), Done("stop")])
    runtime = AgentRuntime(RunLog("child"), await build_agent(settings), approval_broker=broker)
    runtime.set_approval_gate(approve)
    try:
        await runtime.submit("goal", dependencies=TurnDependencies(
            adapter=source, scheduler=scheduler, request=request(),
        ))
        await runtime.wait()
        assert terminal(runtime.log) == ["completed"]
        assert len(identities) == len(cards) == 1
        assert identities[0]["session_id"] == cards[0]["session_id"] == runtime.session_id
        assert identities[0]["run_id"] == cards[0]["run_id"] == "child"
        assert source.requests[1].messages[-1]["content"] == "tool evidence"
    finally:
        await runtime.close()


@pytest.mark.parametrize("mode", ["normal", "cancel", "before_start", "error"])
async def test_parent_terminal_is_after_children_cleanup(mode):
    """正常结束、取消、首次调度前取消和图异常都先清理子运行，主终态仅一次。"""
    children = TurnChildren()
    child_started, child_closed = asyncio.Event(), asyncio.Event()

    async def child():
        """模拟需要异步清理的子运行，主终态必须等待 finally 返回。"""
        child_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            child_closed.set()

    children.start(child)
    await child_started.wait()
    adapter = BarrierAdapter("root result")
    graph = await build_agent(LoopSettings())
    if mode == "error":
        class BrokenGraph:
            """模拟图基础设施异常，不将异常伪装成模型失败。"""

            async def astream(self, *args, **kwargs):
                """尚未产生图终态即抛错，由 Runtime 负责补齐。"""
                raise RuntimeError("internal failure")
                yield  # pragma: no cover
        graph = BrokenGraph()
    runtime = AgentRuntime(MemoryLog(), graph)
    cleanup_at_terminal = []
    runtime.subscribe(lambda event: cleanup_at_terminal.append(child_closed.is_set())
                      if event["kind"] == "turn_end" else None)
    try:
        await runtime.submit("root", dependencies=TurnDependencies(
            adapter=adapter, request=request(), children=children,
        ))
        if mode == "before_start":
            await runtime.cancel()
        elif mode != "error":
            await asyncio.wait_for(adapter.started.wait(), 3)
            if mode == "cancel":
                await runtime.cancel()
            else:
                adapter.release.set()
        await asyncio.wait_for(runtime.wait(), 3)
        assert cleanup_at_terminal == [True]
        assert terminal(runtime.log) == [{
            "normal": "completed", "cancel": "cancelled", "before_start": "cancelled", "error": "error",
        }[mode]]
        with pytest.raises(RuntimeError, match="收尾"):
            children.start(child)
    finally:
        await runtime.close()


async def test_repeated_cancel_does_not_cut_child_cleanup_short():
    """主运行在收拢期间再次取消，也必须等到子清理完成才有主终态。"""
    children = TurnChildren()
    started, cleaning, release, closed = [asyncio.Event() for _ in range(4)]

    async def child():
        """子任务清理保持悬挂，便于精确注入重复取消。"""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            closed.set()

    children.start(child)
    await started.wait()
    runtime = AgentRuntime(MemoryLog(), await build_agent(LoopSettings()))
    try:
        await runtime.submit("root", dependencies=TurnDependencies(
            adapter=ScriptedAdapter([TextDelta("done"), Done("stop")]),
            request=request(), children=children,
        ))
        await asyncio.wait_for(cleaning.wait(), 3)
        await runtime.cancel()
        await runtime.cancel()
        assert terminal(runtime.log) == []
        release.set()
        await asyncio.wait_for(runtime.wait(), 3)
        assert closed.is_set()
        assert terminal(runtime.log) == ["cancelled"]
    finally:
        release.set()
        await runtime.close()


async def test_parent_drain_preserves_cleanup_of_already_cancelled_child(monkeypatch):
    """单独停止专家后主回合结束，不得再次取消正在执行 finally 的专家。"""
    children = TurnChildren()
    started, cleaning, release, cleaned, closing = [asyncio.Event() for _ in range(5)]

    async def child():
        """第一次取消进入清理，用屏障保持清理未完成。"""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

    original_close = children.close

    async def observed_close(**kwargs):
        """观察真实图何时进入收拢，不替换实际取消逻辑。"""
        closing.set()
        await original_close(**kwargs)

    monkeypatch.setattr(children, "close", observed_close)
    child_task = children.start(child)
    await started.wait()
    child_task.cancel()
    await cleaning.wait()
    runtime = AgentRuntime(MemoryLog(), await build_agent(LoopSettings()))
    cleanup_at_terminal = []
    runtime.subscribe(lambda event: cleanup_at_terminal.append(cleaned.is_set())
                      if event["kind"] == "turn_end" else None)
    try:
        await runtime.submit("root", dependencies=TurnDependencies(
            adapter=ScriptedAdapter([TextDelta("done"), Done("stop")]), request=request(), children=children,
        ))
        await asyncio.wait_for(closing.wait(), 3)
        # close 已排入 _drain；让出一次调度，观察它是否重发取消。
        await asyncio.sleep(0)
        assert child_task.cancelling() == 1
        assert terminal(runtime.log) == []
        release.set()
        await asyncio.wait_for(runtime.wait(), 3)
        assert cleanup_at_terminal == [True]
        assert terminal(runtime.log) == ["completed"]
    finally:
        release.set()
        await runtime.close()


async def test_recover_after_prestart_cancel_waits_for_children_and_preserves_cancelled_reason():
    """首次调度前取消与 recover 竞争时，恢复入口也要等待子任务清理。"""
    children = TurnChildren()
    started, cleaning, release, cleaned = [asyncio.Event() for _ in range(4)]

    async def child():
        """用受控清理屏障检查所有终态发布时刻。"""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

    children.start(child)
    await started.wait()
    runtime = AgentRuntime(MemoryLog(), await build_agent(LoopSettings()))
    cleanup_at_terminal = []
    runtime.subscribe(lambda event: cleanup_at_terminal.append(cleaned.is_set())
                      if event["kind"] == "turn_end" else None)

    async def release_cleanup():
        """收拢真正开始后才放行；在放行前记录是否已有提前终态。"""
        await cleaning.wait()
        premature = terminal(runtime.log)
        release.set()
        return premature

    releaser = asyncio.create_task(release_cleanup())
    try:
        await runtime.submit("root", dependencies=TurnDependencies(
            adapter=ScriptedAdapter([Done("stop")]), request=request(), children=children,
        ))
        await runtime.cancel()
        # 原图已取消，done 回调的异步结算尚未取锁，recover 在当前协程直接抢先进入。
        await asyncio.sleep(0)
        recovered = await runtime.recover()
        assert await asyncio.wait_for(releaser, 3) == []
        await runtime.wait()
        assert cleanup_at_terminal == [True]
        assert terminal(runtime.log) == ["cancelled"]
        assert [e["data"]["reason"] for e in recovered if e["type"] == "turn/end"] == ["cancelled"]
        assert await runtime.recover() == []
    finally:
        release.set()
        releaser.cancel()
        await asyncio.gather(releaser, return_exceptions=True)
        await runtime.close()


async def consume(adapter):
    """完整消费一个模型流，测试实际派发和关闭次数。"""
    return [chunk async for chunk in adapter.stream(request())]


async def test_shared_budget_last_slot_is_atomic_and_counts_failed_dispatch():
    """两个运行争用一份剩余额度时只有一个能派发，失败不自动返还额度。"""
    budget = ModelCallBudget(max_calls=1, max_concurrent=2, max_calls_per_run=1)
    sources = [ScriptedAdapter([Done("stop")]), ScriptedAdapter([Done("stop")])]
    results = await asyncio.gather(*(consume(BudgetedAdapter(source, budget, str(index)))
                                     for index, source in enumerate(sources)), return_exceptions=True)
    assert sum(isinstance(result, LlmRequestError) for result in results) == 1
    assert sum(len(source.requests) for source in sources) == 1
    error = next(result for result in results if isinstance(result, LlmRequestError))
    assert error.public_code == "BUDGET_EXCEEDED" and not error.retryable
    assert budget.snapshot()["calls"] == 1
    assert budget.snapshot()["active"] == 0


async def test_loop_retry_uses_shared_budget_and_stops_without_an_extra_provider_call():
    """用真实图发起模型重试，额度耗尽必须形成可追溯失败且不再访问供应商。"""
    budget = ModelCallBudget(max_calls=1, max_concurrent=1, max_calls_per_run=1)

    class FailingAdapter:
        """记录供应商派发，第一次调用返回可重试传输错误。"""

        calls = 0

        async def stream(self, model_request):
            """在请求已派发后失败，不能当作未消耗调用。"""
            self.calls += 1
            raise ConnectionError("private upstream detail")
            yield  # pragma: no cover

    source = FailingAdapter()
    runtime = AgentRuntime(RunLog("child"), await build_agent(LoopSettings(dsh_model_retry_delay_seconds=0)))
    try:
        await runtime.submit("goal", dependencies=TurnDependencies(
            adapter=BudgetedAdapter(source, budget, "child"), request=request(),
        ))
        await runtime.wait()
        assert source.calls == 1
        assert terminal(runtime.log) == ["error"]
        errors = [event["data"]["error_code"] for event in runtime.log.read()
                  if event["type"] == "assistant/attempt"]
        assert errors == ["UPSTREAM", "BUDGET_EXCEEDED"]
    finally:
        await runtime.close()


async def test_waiting_for_model_capacity_does_not_spend_budget_and_cancel_releases_slot():
    """模型并发队列中的取消不扣费，已派发但取消的调用保留消耗记录。"""
    budget = ModelCallBudget(max_calls=3, max_concurrent=1, max_calls_per_run=2)
    first, second = BarrierAdapter("first"), BarrierAdapter("second")
    running = asyncio.create_task(consume(BudgetedAdapter(first, budget, "a")))
    await asyncio.wait_for(first.started.wait(), 3)
    waiting = asyncio.create_task(consume(BudgetedAdapter(second, budget, "b")))
    await asyncio.sleep(0)
    assert not second.started.is_set()
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)
    assert first.closed.is_set()
    assert budget.snapshot() == {"calls": 1, "active": 0, "by_run": {"a": 1}}
    second.release.set()
    await consume(BudgetedAdapter(second, budget, "b"))
    assert budget.snapshot()["calls"] == 2


async def test_per_run_limit_does_not_spend_other_run_allowance_and_closed_budget_rejects():
    """单运行耗尽不能吃掉另一个运行的额度；关闭之后队列不得再派发。"""
    budget = ModelCallBudget(max_calls=3, max_concurrent=1, max_calls_per_run=1)
    source = ScriptedAdapter([Done("stop")], [Done("stop")])
    await consume(BudgetedAdapter(source, budget, "a"))
    with pytest.raises(LlmRequestError):
        await consume(BudgetedAdapter(source, budget, "a"))
    await consume(BudgetedAdapter(source, budget, "b"))
    budget.close()
    with pytest.raises(LlmRequestError) as caught:
        await consume(BudgetedAdapter(source, budget, "c"))
    assert caught.value.public_code == "CONCURRENCY"
    assert len(source.requests) == 2


async def test_children_limit_is_cumulative_and_rejection_does_not_create_coroutine():
    """已完成子运行不返还实例额度，拒绝前不调用协程工厂。"""
    children = TurnChildren(max_children=1)

    async def child():
        """一个立即完成的子运行。"""
        return 1

    assert await children.start(child) == 1
    with pytest.raises(RuntimeError, match="上限"):
        children.start(child)
    await children.close()
    await children.close()


@pytest.mark.parametrize("run_id", ["", " ", 123])
async def test_invalid_child_identity_cannot_fall_back_to_parent_namespace(run_id):
    """非法 run_id 必须在创建运行时前拒绝。"""
    with pytest.raises(ValueError):
        execution_key(RunLog(run_id))
