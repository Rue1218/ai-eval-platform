"""M4 编排层路由单测（阶段 1：O-A1~O-A4）；不触碰 WS/DB/真实模型。"""

import asyncio

import pytest

from app.adapters import StreamAborted
from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.agent.plan_solve import build_plan_solve_subgraph, plan_solve_route
from app.errors import AppError, ErrorCode
from app.harness.memory import GraphState, SerializableRequest
from app.harness.orchestration import decide_mode, detect_plan_intent
from app.llm import ModelRequest, ModelResponse, ModelStreamEvent


def _serializable(text: str = "你好") -> SerializableRequest:
    """构造可序列化请求投影（不含回调/api_key）。"""
    # 本文件桩网关输出 legacy ReAct JSON,显式固定 legacy 模式
    # (平台默认已切换 native,见 a9c41b7e2d10)。
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
            "tool_call_mode": "legacy",
        },
        messages=({"role": "user", "content": text},),
    )


class _FakeGateway:
    """记录调用并返回固定流事件 / ReAct 收尾 JSON 的网关桩。"""

    def __init__(self) -> None:
        self.stream_calls: list[ModelRequest] = []
        self.invoke_calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
        """规划后的 ReAct 控制回合走 invoke，返回合法 done JSON。"""
        self.invoke_calls.append(request)
        return ModelResponse(
            text=(
                '{"protocol":"react","version":"react.v1",'
                '"thought":"按规划向用户说明确认卡入队","tool":null,'
                '"arguments":{},"done":true}'
            ),
            latency_ms=2,
        )

    def stream(self, request: ModelRequest, config: dict | None = None):
        """记录请求并返回推理/正文事件（可注入取消回调）。"""
        self.stream_calls.append(request)
        abort = None
        if config:
            abort = config.get("configurable", {}).get("abort", {}).get("should_abort")
        if abort is not None and abort():
            raise StreamAborted()
        return iter(
            [
                ModelStreamEvent(kind="reasoning", text="先判断"),
                ModelStreamEvent(kind="content", text="流式答案"),
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text="流式答案", latency_ms=2),
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


def _event_kinds(events: list[tuple[str, dict]]) -> list[str]:
    """从 updates 增量中提取全部 pending_events kind。"""
    return [
        event["kind"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]


def _error_payloads(events: list[tuple[str, dict]]) -> list[dict]:
    """从 updates 增量中提取 error 事件 payload。"""
    return [
        event["payload"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
        if event["kind"] == "error"
    ]


def test_routing_slash_goes_direct_no_model_call() -> None:
    """O-A1：斜杠 text 进 Direct 分支，不调模型；/help 必须发 completed 收尾。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("/help"))
    assert gateway.stream_calls == []
    assert _event_kinds(events) == ["assistant_message", "response.completed"]
    completed = [
        event["payload"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
        if event["kind"] == "response.completed"
    ]
    assert completed == [{"finish_reason": "stop", "role": "assistant"}]


def test_routing_plain_text_goes_chat() -> None:
    """O-A1：非斜杠 text 进 Chat 分支，调模型并投影事件。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    assert len(gateway.stream_calls) == 1
    custom = [chunk for mode, chunk in events if mode == "custom"]
    assert [(c["kind"], c["text"]) for c in custom] == [
        ("reasoning", "先判断"),
        ("content", "流式答案"),
    ]
    assert _event_kinds(events) == ["assistant_message", "response.completed"]


def test_unknown_slash_returns_validation() -> None:
    """O-A1：未知斜杠返回 VALIDATION error 事件，不调模型，并以 completed(error) 收尾。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("/nope"))
    assert gateway.stream_calls == []
    assert _error_payloads(events) == [
        {"code": "VALIDATION", "message": "未知斜杠命令：/nope"}
    ]
    assert _event_kinds(events) == ["error", "response.completed"]
    completed = [
        event["payload"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
        if event["kind"] == "response.completed"
    ]
    assert completed == [{"finish_reason": "error", "role": "assistant"}]


def test_session_control_slash_returns_defense_hint() -> None:
    """/cancel /stress /compact 由 ws.py 直连；图内仅防御提示 + completed(error)。"""
    for command in ("/cancel", "/stress", "/compact"):
        gateway = _FakeGateway()
        events = _collect(LangGraphAgent(gateway), _serializable(command))
        assert gateway.stream_calls == []
        assert _error_payloads(events) == [
            {"code": "VALIDATION", "message": f"{command} 由平台会话控制处理，无需发送"}
        ]
        assert _event_kinds(events) == ["error", "response.completed"]


def test_help_text_lists_cancel_and_stress() -> None:
    """/help 帮助文本列出已开放的 /cancel 与 /stress。"""
    from app.agent.routing import HELP_TEXT

    assert "/compact：压缩本会话模型窗口" in HELP_TEXT
    assert "/cancel：取消本会话未完成任务" in HELP_TEXT
    assert "/stress：打开先评后压确认卡" in HELP_TEXT
    assert "后续版本开放" not in HELP_TEXT


def test_graph_state_has_no_should_abort_field() -> None:
    """O-A2：should_abort 不出现在 GraphState 字段中（反射断言）。"""
    annotations = GraphState.__annotations__
    assert "should_abort" not in annotations
    # 回调不得以任何形式入 State
    assert "request" in annotations  # 投影（SerializableRequest，无回调）


def test_should_abort_via_runnable_config_triggers_stream_aborted() -> None:
    """O-A3：取消回调经 RunnableConfig.configurable 注入，取消触发 StreamAborted。"""
    gateway = _FakeGateway()
    agent = LangGraphAgent(gateway)
    config = {"configurable": {"abort": {"should_abort": lambda: True}}}
    with pytest.raises(StreamAborted):
        _collect(agent, _serializable("你好"), config=config)


def test_should_abort_not_triggered_when_absent() -> None:
    """O-A3：未注入取消回调时正常完成（向后兼容）。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    assert _event_kinds(events) == ["assistant_message", "response.completed"]


def test_chat_assemble_injects_skill_hints_without_tools() -> None:
    """CX-4/CX-5：Chat 走 assemble，常驻 Skill Hint，不注入工具定义。"""
    gateway = _FakeGateway()
    _collect(
        LangGraphAgent(gateway),
        _serializable("你好"),
        config={"configurable": {"session": {"compact_summary": "上次已闲聊问好"}}},
    )
    request = gateway.stream_calls[0]
    assert request.tools == ()
    assert "【可见技能】" in (request.system or "")
    assert "基准评测" in (request.system or "")
    assert "【当前技能工作流】" not in (request.system or "")
    assert "三协议调用" not in (request.system or "")
    assert "【会话摘要】" in (request.system or "")
    assert "上次已闲聊问好" in (request.system or "")


def test_detect_plan_intent_requires_complex_intent() -> None:
    """P0：单工具不升级；多技能、多短工具链、确认卡或清单才为 True。"""
    assert detect_plan_intent("帮我评测一下") is False
    assert detect_plan_intent("读取这个文件") is False
    assert detect_plan_intent("评测 Qwen 并生成测试用例") is True
    assert detect_plan_intent("先评后压") is True
    assert detect_plan_intent("按任务清单做知识库评测") is True
    assert detect_plan_intent("run benchmark and testcase") is True
    assert detect_plan_intent("先 read 日志，再用 bash 统计，最后 write 报告") is True


def test_decide_mode_plan_solve_and_react_priority() -> None:
    """P0：多槽或多短工具链走 plan_solve；单工具仍 ReAct；附件强制 react。"""
    assert decide_mode("评测并生成用例", has_multi_slots=True) == "plan_solve"
    assert decide_mode(
        "先 read 日志，再用 bash 统计，最后 write 报告", has_multi_slots=True
    ) == "plan_solve"
    assert decide_mode("读取这个文件") == "react"
    assert decide_mode(
        "评测并生成用例",
        has_multi_slots=True,
        has_attachments=True,
    ) == "react"
    assert decide_mode("你好") == "chat"


def test_routing_short_tool_chain_plans_then_reacts() -> None:
    """多短工具链：规划模型降级后仍产出内部 PlanArtifact，不输出用户协议正文。"""
    gateway = _FakeGateway()
    request = _serializable("先 read 日志，再用 bash 统计，最后 write 报告")
    events = _collect(LangGraphAgent(gateway), request)
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    plan = next(event["payload"] for event in pending if event["kind"] == "plan")
    assert plan["intent"] == "执行多短工具链"
    assert plan["tools_needed"] == ["task", "read", "write", "bash"]
    assert "<PLAN>" not in str(plan)


def test_short_tool_chain_rejects_user_style_plan_wrapper() -> None:
    """规划器返回用户式 <PLAN> 时，必须降级平台计划而非透传为助手正文。"""

    class _WrappedPlanGateway(_FakeGateway):
        def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
            if "任务规划" in str(request.messages):
                self.invoke_calls.append(request)
                return ModelResponse(
                    text='<PLAN>{"steps":[{"action":"bash","input":"ls"}]}</PLAN>',
                    latency_ms=2,
                )
            return super().invoke(request, config)

    gateway = _WrappedPlanGateway()
    events = _collect(
        LangGraphAgent(gateway),
        _serializable("先 read 日志，再用 bash 统计，最后 write 报告"),
    )
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    plan = next(event["payload"] for event in pending if event["kind"] == "plan")
    messages = [
        str(event["payload"].get("text") or "")
        for event in pending
        if event["kind"] == "assistant_message"
    ]
    assert plan["intent"] == "执行多短工具链"
    assert not any("<PLAN>" in text for text in messages)


def test_routing_multi_skill_plans_then_react_then_reflect() -> None:
    """多技能：完整 PlanArtifact → ReAct 注入规划 → reflect 统一发 completed。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("帮我做基准评测并生成测试用例"))
    assert gateway.stream_calls == []
    # LLM Planner 已接线：规划一次短调用（产物非法降级 L0）+ ReAct 一次控制调用；
    # 桩网关返回 react JSON 无法解析为 plan.v1，计划仍由 L0 规则产出。
    assert len(gateway.invoke_calls) == 2
    assert "【当前规划】" in str(gateway.invoke_calls[1].system)
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    kinds = [event["kind"] for event in pending]
    assert kinds.count("response.completed") == 1
    assert kinds[-1] == "response.completed"
    assert kinds.index("plan") < kinds.index("assistant_message")
    assert kinds.index("assistant_message") < kinds.index("response.completed")
    assert "tool_call" not in kinds
    assert "error" not in kinds
    plan_payload = next(event["payload"] for event in pending if event["kind"] == "plan")
    assert {"intent", "slots", "budget", "notes", "tools_needed", "delivery"} <= set(
        plan_payload
    )
    steps = plan_payload["slots"]["steps"]
    assert 3 <= len(steps) <= 7
    assert plan_payload["tools_needed"] == ["task"]
    reflect_thoughts = [
        event
        for event in pending
        if event["kind"] == "thought" and event["payload"].get("stage") == "reflect"
    ]
    assert reflect_thoughts
    assert kinds.index("plan") < kinds.index("response.completed")
    assert pending.index(reflect_thoughts[0]) < len(pending) - 1
    budget_updates = [
        value.get("budget")
        for mode, chunk in events
        if mode == "updates"
        for value in chunk.values()
        if isinstance(value, dict) and isinstance(value.get("budget"), dict)
    ]
    assert budget_updates
    # 规划短调用已消费一次：首次预算投影为计划预算扣减 1
    assert budget_updates[0]["model_calls"] == plan_payload["budget"]["model_calls"] - 1


def test_routing_plan_react_error_completes_with_error() -> None:
    """规划后 ReAct 硬错误：completed(error)，不再进 reflect 发 stop。"""

    class _BoomGateway(_FakeGateway):
        def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
            self.invoke_calls.append(request)
            raise AppError(ErrorCode.UPSTREAM, "上游失败")

    events = _collect(
        LangGraphAgent(_BoomGateway()),
        _serializable("帮我做基准评测并生成测试用例"),
    )
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    kinds = [event["kind"] for event in pending]
    assert "error" in kinds
    assert kinds.count("response.completed") == 1
    assert kinds[-1] == "response.completed"
    completed = next(event for event in pending if event["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "error"
    assert not any(
        event["kind"] == "thought" and event["payload"].get("stage") == "reflect"
        for event in pending
    )


def test_invoke_plan_solve_returns_model_response() -> None:
    """非流式入口对规划回合返回 ReAct 正文，不再误判为 Direct。"""
    response = LangGraphAgent(_FakeGateway()).invoke(
        _serializable("帮我做基准评测并生成测试用例")
    )
    assert "确认卡" in response.text


class _PlanAwareGateway(_FakeGateway):
    """规划阶段返回合法 plan.v1 JSON，其余调用沿用 ReAct done JSON。"""

    def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
        self.invoke_calls.append(request)
        if "任务规划" in str(request.messages):
            return ModelResponse(
                text=(
                    '{"protocol": "plan", "version": "plan.v1", '
                    '"intent": "模型规划意图", "skill_id": "skill-benchmark", '
                    '"slots": {"steps": ["一步", "两步", "三步"]}, '
                    '"tools_needed": ["task"], "delivery": "confirm", '
                    '"budget": {"model_calls": 6, "tool_turns": 6}, '
                    '"allows_replan": true, "notes": ""}'
                ),
                latency_ms=2,
            )
        return super().invoke(request, config)


def test_plan_solve_uses_llm_planner_artifact() -> None:
    """LLM Planner：规划短调用产出合法 plan.v1 时，图直接采用模型计划。"""
    gateway = _PlanAwareGateway()
    events = _collect(
        LangGraphAgent(gateway),
        _serializable("帮我做基准评测并生成测试用例"),
    )
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    kinds = [event["kind"] for event in pending]
    assert "error" not in kinds
    assert kinds.count("response.completed") == 1
    plan_payload = next(event["payload"] for event in pending if event["kind"] == "plan")
    assert plan_payload["intent"] == "模型规划意图"
    assert plan_payload["slots"]["steps"] == ["一步", "两步", "三步"]
    react_systems = [
        str(call.system or "")
        for call in gateway.invoke_calls
        if "【当前技能工作流】" in str(call.system or "")
    ]
    assert react_systems, "选中 skill-benchmark 后 ReAct 须按需注入工作流"
    assert "三协议调用" in react_systems[0]
    assert "六策略 LLM" not in react_systems[0]
    # 规划短调用 + ReAct 控制调用 + done 后无工具最终回答调用（基线行为，非本次新增）
    assert len(gateway.invoke_calls) == 3
    final_message = next(event for event in pending if event["kind"] == "assistant_message")
    # 收尾正文来自无工具最终回答（桩网关回 react JSON 无正文 → 中性兑底），非 Observation 原文
    assert "一步" not in final_message["payload"]["text"]


def test_plan_solve_disabled_skill_returns_validation() -> None:
    """SK-4：规划产出 skill-rag 时整轮 VALIDATION，不得发确认卡或工作流。"""

    class _RagPlanGateway(_FakeGateway):
        def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
            self.invoke_calls.append(request)
            if "任务规划" in str(request.messages):
                return ModelResponse(
                    text=(
                        '{"protocol": "plan", "version": "plan.v1", '
                        '"intent": "知识库评测", "skill_id": "skill-rag", '
                        '"slots": {"steps": ["确认知识库", "入队", "等待报告"]}, '
                        '"tools_needed": ["task"], "delivery": "confirm", '
                        '"budget": {"model_calls": 4, "tool_turns": 4}, '
                        '"allows_replan": true, "notes": ""}'
                    ),
                    latency_ms=2,
                )
            return super().invoke(request, config)

    events = _collect(
        LangGraphAgent(_RagPlanGateway()),
        _serializable("按任务清单做知识库评测"),
    )
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    kinds = [event["kind"] for event in pending]
    assert "plan" not in kinds
    assert "confirm" not in kinds
    assert kinds.count("response.completed") == 1
    error = next(event for event in pending if event["kind"] == "error")
    assert error["payload"]["code"] == "VALIDATION"
    assert "技能未启用" in error["payload"]["message"]


def test_plan_solve_fallback_on_upstream_error() -> None:
    """规划短调用上游异常：降级 L0 规则，整轮仍正常收尾（Q3 失败走 L0）。"""

    class _PlanFailGateway(_FakeGateway):
        def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
            if "任务规划" in str(request.messages):
                self.invoke_calls.append(request)
                raise AppError(ErrorCode.UPSTREAM, "上游失败")
            return super().invoke(request, config)

    events = _collect(
        LangGraphAgent(_PlanFailGateway()),
        _serializable("帮我做基准评测并生成测试用例"),
    )
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    kinds = [event["kind"] for event in pending]
    assert "plan" in kinds
    assert "error" not in kinds
    assert kinds[-1] == "response.completed"


def test_plan_solve_illegal_plan_clears_and_stops() -> None:
    """非法存量 plan 必须清空，条件边不得再进 ReAct。"""
    out = build_plan_solve_subgraph()["plan_solve"]({"plan": {"intent": "坏的"}})
    assert out["plan"] is None
    assert plan_solve_route({"plan": out["plan"]}) == "end"
    assert [event["kind"] for event in out["pending_events"]] == [
        "error",
        "response.completed",
    ]


def test_node_events_emitted_via_pending_events() -> None:
    """O-A4：节点产出 NodeEvent 写入 pending_events，经 updates 可见。"""
    gateway = _FakeGateway()
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    assert all(event["event_version"] == "event.v1" for event in pending)
    # pending_events 是纯数据（可序列化，无回调/连接）
    import json

    json.dumps(pending)
