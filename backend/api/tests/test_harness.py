"""Harness 规划 / 复核 / 观察脱敏纯逻辑单测（不连库、不连上游）。"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from app.agent.context import run_compact
from app.agent.defaults import HARD_MAX_TOOL_ROUNDS, MAX_MODEL_CALLS, is_long_tool
from app.agent.harness import (
    _chat_reply,
    handle_cancel_task,
    handle_confirm_ack,
    should_emit_stage_thoughts,
)
from app.agent.mcp_tools import redact_secrets, truncate_tool_data
from app.agent.persona import PERSONA_SYSTEM, turn_system
from app.agent.plan import (
    PlanArtifact,
    TurnBudget,
    _call_plan_model,
    apply_prefs_suggestions,
    classify_intent_l0,
    is_smalltalk,
    l0_plan,
    merge_replan,
    parse_json_object,
    plan_from_slash,
    run_plan,
    run_replan,
    sanitize_plan,
)
from app.agent.react import McpStep, ReactArtifact, build_proposed_spec, parse_mcp_step, run_react
from app.agent.reflect import ReflectArtifact, maybe_model_check, run_gates
from app.agent.slash import (
    is_unknown_slash,
    parse_slash,
    unknown_command_text,
)
from app.agent.turn_mode import (
    TurnMode,
    allows_model_check,
    allows_replan,
    refine_turn_mode,
    resolve_turn_mode,
    select_turn_mode,
    uses_react_llm,
)
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.trace import TraceContext
from app.harness.llm.client import AgentJsonStreamResult
from app.models import Dataset, ProtocolProfile, Task, User
from app.models import Session as AgentSession


def _turn_ctx() -> dict:
    """阶段 2：测试夹具必须显式构造同一 Turn 的 trace/cancel。"""
    trace = TraceContext.for_turn()
    return {"trace": trace, "cancel": CancellationToken(turn_id=trace.turn_id)}


def test_chat_reply_persists_completed_reasoning_snapshot(monkeypatch):
    """流式思考只增量发送，成功结束后必须补一帧可回放的完整快照。"""

    class _Db:
        def close(self):
            return None

    def _stream(*_args, **_kwargs):
        yield "reasoning", "先检查"
        yield "reasoning", "上下文"
        yield "answer", "你好"

    monkeypatch.setattr("app.llm.stream_agent_model", _stream)
    monkeypatch.setattr("app.agent.harness.SessionLocal", lambda: _Db())
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return len(events)

    result = asyncio.run(
        _chat_reply(
            None,
            "你好",
            [],
            TurnBudget(),
            stop=threading.Event(),
            compact_summary=None,
            skill_id=None,
            emit=_emit,
            **_turn_ctx(),
        )
    )

    assert result == "你好"
    assert any(event == "thought" and payload.get("stream") == "think" for event, payload in events)
    assert ("thought", {"text": "先检查上下文", "stream": "think_final"}) in events


def test_stream_mcp_step_emits_native_reasoning(monkeypatch):
    """ReAct 决策流式下发推理链，并在成功后落 think_final。"""

    class _Db:
        def close(self):
            return None

    def _stream(*_args, **_kwargs):
        yield "reasoning", "先想要不要生图"
        yield "content", '{"thought":"调用生图","tool":"image.generate","arguments":{},"done":false,"reply":""}'

    monkeypatch.setattr("app.llm.stream_agent_model", _stream)
    monkeypatch.setattr("app.db.SessionLocal", lambda: _Db())
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return len(events)

    from app.agent.react import _stream_mcp_step

    step = asyncio.run(
        _stream_mcp_step(
            system="sys",
            payload={"text": "帮我画一张图"},
            stop=threading.Event(),
            emit=_emit,
            **_turn_ctx(),
        )
    )
    assert step.tool == "image.generate"
    assert step.reasoning_text == "先想要不要生图"
    assert any(event == "thought" and payload.get("stream") == "think" for event, payload in events)
    assert ("thought", {"text": "先想要不要生图", "stream": "think_final"}) in events


def test_stream_mcp_step_think_arrives_before_slow_content(monkeypatch):
    """CoT：思考增量必须在正文 JSON 完成前到达，不得整包空等。"""

    class _Db:
        def close(self):
            return None

    think_at: list[float] = []
    started = time.perf_counter()

    def _stream(*_args, **_kwargs):
        yield "reasoning", "步骤一"
        time.sleep(0.2)
        yield "reasoning", "步骤二"
        time.sleep(0.2)
        yield "content", '{"thought":"问候","tool":null,"arguments":{},"done":true,"reply":"你好"}'

    monkeypatch.setattr("app.llm.stream_agent_model", _stream)
    monkeypatch.setattr("app.db.SessionLocal", lambda: _Db())

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "thought" and payload.get("stream") == "think":
            think_at.append(time.perf_counter() - started)
        return 1

    from app.agent.react import _stream_mcp_step

    step = asyncio.run(
        _stream_mcp_step(
            system="sys",
            payload={"text": "你好"},
            stop=threading.Event(),
            emit=_emit,
            **_turn_ctx(),
        )
    )
    elapsed = time.perf_counter() - started
    assert step.reply == "你好"
    assert step.reasoning_text == "步骤一步骤二"
    assert len(think_at) == 2
    # 第一块思考链应几乎立刻到达，不能等完整正文。
    assert think_at[0] < 0.12
    # 第二步在第一次休眠之后、正文结束之前。
    assert think_at[1] >= 0.18
    assert think_at[1] < elapsed
    assert elapsed >= 0.38


def test_chat_and_help_skip_stage_thoughts():
    """闲聊与 /help 不发规划/复核思考卡，避免三张「已思考」。"""
    assert should_emit_stage_thoughts("chat", None) is False
    assert should_emit_stage_thoughts("inspect", "help") is False
    assert should_emit_stage_thoughts("inspect", "status") is False
    assert should_emit_stage_thoughts("benchmark", None) is True
    assert should_emit_stage_thoughts("benchmark", "benchmark") is True
    assert should_emit_stage_thoughts("inspect", None, TurnMode.REACT_ONLY) is False
    assert should_emit_stage_thoughts("benchmark", "benchmark", TurnMode.PLAN_SOLVE) is True


def test_select_turn_mode_by_task_shape():
    """最小内核：斜杠直达；自然语言一律走思考链循环。"""
    assert select_turn_mode("你好", parse_slash("你好")) is TurnMode.REACT_ONLY
    assert select_turn_mode("/compact", parse_slash("/compact")) is TurnMode.DIRECT
    assert select_turn_mode("/benchmark", parse_slash("/benchmark")) is TurnMode.DIRECT
    portrait = "帮我生成一张竖幅户外人像摄影，明暗对比柔和"
    assert select_turn_mode(portrait, parse_slash(portrait)) is TurnMode.REACT_ONLY
    assert select_turn_mode("列出协议档", parse_slash("列出协议档")) is TurnMode.REACT_ONLY
    assert select_turn_mode("帮我评一下", parse_slash("帮我评一下")) is TurnMode.REACT_ONLY
    assert uses_react_llm(TurnMode.REACT_ONLY, command=None, slash_fill_first=False) is True
    assert uses_react_llm(TurnMode.CHAT, command=None, slash_fill_first=False) is True
    assert allows_replan(TurnMode.REACT_ONLY) is False
    assert allows_model_check(TurnMode.CHAT) is False
    refined = refine_turn_mode(
        TurnMode.INTENT, intent="chat", tools_needed=["image.generate"], delivery="text"
    )
    assert refined is TurnMode.REACT_ONLY
    assert refine_turn_mode(TurnMode.INTENT, intent="chat", tools_needed=[], delivery="text") is TurnMode.REACT_ONLY


def test_l0_chat_vs_benchmark_and_testcase():
    """L0：闲聊不胡乱下单；评测关键词进 benchmark；PRD 进 testcase。"""
    assert classify_intent_l0("介绍一下你")[0] == "chat"
    assert classify_intent_l0("你好")[0] == "chat"
    assert classify_intent_l0("今天天气如何")[0] == "chat"
    assert classify_intent_l0("帮我生成一首轻盈的音乐")[0] == "chat"
    assert classify_intent_l0("对比两个模型的基准表现")[0] == "benchmark"
    assert classify_intent_l0("帮我评一下")[0] == "benchmark"
    assert classify_intent_l0("你好，帮我评一下")[0] == "benchmark"
    assert classify_intent_l0("根据 PRD 生成测试用例")[0] == "testcase"
    assert classify_intent_l0("评测知识库召回效果")[0] == "rag"
    intent, stress = classify_intent_l0("先评后压 10 QPS")
    assert intent == "benchmark" and stress is True
    # 摄影提示词里的「对比」不得当成评测
    portrait = "帮我生成一张竖幅户外人像摄影，明暗对比柔和"
    assert classify_intent_l0(portrait)[0] == "chat"
    assert is_smalltalk("你好") is True
    assert is_smalltalk("你好，帮我评一下") is False
    assert is_smalltalk("随便说说") is False


def test_l0_plan_missing_slots_clarify_not_confirm():
    """D1：L0 缺槽时 delivery=clarify，仍进复核、不出假确认卡。"""
    plan = l0_plan("帮我评一下")
    assert plan.intent == "benchmark"
    assert "profile_ids" in plan.slots["missing"]
    assert plan.delivery == "clarify"
    assert plan.tools_needed == []


def test_sanitize_plan_clamps_budget_and_nulls_illegal_skill():
    """HAR-PLAN-02：max_tool_rounds 硬顶 5；非法 skill_id 置 null。"""
    artifact = sanitize_plan(
        {
            "intent": "benchmark",
            "skill_id": "skill-unknown",
            "slots": {"filled": {"kind": "benchmark", "foo": 1}, "missing": ["profile_ids"]},
            "tools_needed": ["model.list"],
            "delivery": "not-a-delivery",
            "budget": {"max_tool_rounds": 99},
            "notes": "规划：测试",
        }
    )
    assert artifact.skill_id is None
    assert artifact.delivery == "clarify"
    assert artifact.budget["max_tool_rounds"] == HARD_MAX_TOOL_ROUNDS
    assert "foo" not in artifact.slots["filled"]
    assert artifact.loop == "plan_solve"
    assert artifact.complexity == "high"


def test_sanitize_plan_reads_loop_and_complexity():
    artifact = sanitize_plan(
        {
            "intent": "chat",
            "skill_id": None,
            "slots": {"filled": {}, "missing": []},
            "tools_needed": [],
            "delivery": "text",
            "budget": {"max_tool_rounds": 1},
            "notes": "规划：闲聊",
            "complexity": "low",
            "loop": "chat",
        }
    )
    assert artifact.loop == "chat"
    assert artifact.complexity == "low"
    assert "loop" not in artifact.as_dict()


def test_resolve_turn_mode_nl_always_react():
    """自然语言即使历史 loop=chat 也走思考链循环，不再二次闲聊生成。"""
    text = "帮我评一下这张图好不好看"
    plan = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=[],
        delivery="text",
        budget={"max_tool_rounds": 1},
        notes="规划：闲聊",
        source="llm",
        loop="chat",
        complexity="low",
    )
    assert resolve_turn_mode(text=text, parsed=parse_slash(text), plan=plan) is TurnMode.REACT_ONLY


def test_resolve_turn_mode_forces_react_when_image_tool_present():
    """inject 后含 image.generate 时覆盖模型误选的 plan_solve。"""
    text = "帮我生成一张竖幅户外人像摄影"
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids"]},
        tools_needed=["image.generate"],
        delivery="clarify",
        budget={"max_tool_rounds": 4},
        notes="规划：误判",
        source="llm",
        loop="plan_solve",
        complexity="high",
    )
    assert resolve_turn_mode(text=text, parsed=parse_slash(text), plan=plan) is TurnMode.REACT_ONLY


def test_parse_plan_json_rejects_plain_text():
    with pytest.raises(ValueError):
        parse_json_object("抱歉，我不明白你的意思。")


def test_slash_stress_never_kind_stress():
    """已删除的业务斜杠不能再创建业务规划。"""
    parsed = parse_slash("/stress")
    plan = plan_from_slash(parsed, prefs={}, attachments=[])
    assert plan.intent == "chat"
    assert plan.tools_needed == []


def test_slash_testcase_missing_source():
    parsed = parse_slash("/testcase")
    plan = plan_from_slash(parsed, prefs={}, attachments=[])
    assert plan.intent == "chat"
    assert plan.tools_needed == []


def test_gates_reject_long_tool():
    """TC-12：tools_needed 含长工具 → reject VALIDATION。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": []},
        tools_needed=["benchmark.run"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    session = AgentSession(id="s1", user_id="u1", title="t")
    artifact = run_gates(_FakeDb(), session=session, plan=plan, react=ReactArtifact())
    assert artifact.verdict == "reject"
    assert artifact.error_code == ErrorCode.VALIDATION.value


def test_gates_hallucinated_id_clarify():
    """TC-04 / TC-20a：规划产物含工具结果外的 ID → clarify，不出卡。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": []},
        tools_needed=["model.list", "dataset.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="slash",
    )
    react = ReactArtifact(
        observations=[
            {
                "name": "model.list",
                "ok": True,
                "latency_ms": 1,
                "data_summary": {"count": 1, "ids": ["p-real"]},
            },
            {
                "name": "dataset.list",
                "ok": True,
                "latency_ms": 1,
                "data_summary": {"count": 1, "ids": ["d-real"]},
            },
        ],
        proposed_spec={
            "kind": "benchmark",
            "profile_ids": ["p-fake"],
            "dataset_id": "d-real",
            "run": {"sample_size": 1000},
            "with_stress": False,
        },
        known_ids=["p-real", "d-real"],
    )
    session = AgentSession(id="s1", user_id="u1", title="t")
    artifact = run_gates(_FakeDb(), session=session, plan=plan, react=react)
    assert artifact.verdict == "reject"


def test_gates_kind_stress_rejected():
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-stress",
        slots={"filled": {"kind": "stress"}, "missing": []},
        tools_needed=[],
        delivery="confirm",
        budget={"max_tool_rounds": 0},
        notes="规划",
        source="slash",
    )
    react = ReactArtifact(proposed_spec={"kind": "stress", "parent_task_id": "x"})
    session = AgentSession(id="s1", user_id="u1", title="t")
    artifact = run_gates(_FakeDb(), session=session, plan=plan, react=react)
    assert artifact.verdict == "reject"


def test_redact_and_truncate_observation():
    data = {
        "api_key": "sk-live",
        "items": [{"id": f"i-{i}", "name": f"n-{i}"} for i in range(30)],
    }
    redacted = redact_secrets(data)
    assert redacted["api_key"] == "***"
    truncated = truncate_tool_data(data)
    assert truncated["truncated"] is True
    assert len(truncated["items"]) == 20


def test_is_long_tool():
    assert is_long_tool("benchmark.run")
    assert not is_long_tool("model.list")


def test_parse_slash_benchmark_args():
    parsed = parse_slash("/benchmark smoke-20")
    assert parsed.command == "benchmark"
    assert parsed.args == "smoke-20"
    assert parse_slash("对比两个模型").is_slash is False


def test_unknown_slash_foo_is_not_chat():
    """``/foo`` 正则能解析出命令名，仍须按未知命令而不是闲聊。"""
    parsed = parse_slash("/foo")
    assert parsed.is_slash is True
    assert parsed.command == "foo"
    assert is_unknown_slash(parsed) is True
    assert is_unknown_slash(parse_slash("/benchmark")) is True
    assert is_unknown_slash(parse_slash("你好")) is False
    help_text = unknown_command_text()
    assert help_text.startswith("未知命令。")
    assert "/compact" in help_text


def test_turn_system_injects_summary_and_skill():
    """压缩摘要与技能说明进入 system，不能只靠缩短后的 window_rows。"""
    text = turn_system(
        PERSONA_SYSTEM,
        skill_id="skill-benchmark",
        compact_summary="用户上次要对比两个模型。",
    )
    assert "技能 · 基准对比" in text
    assert "压缩摘要" in text
    assert "对比两个模型" in text
    assert PERSONA_SYSTEM in text
    bare = turn_system(PERSONA_SYSTEM)
    assert "压缩摘要" not in bare


def test_prefs_do_not_attach_stress_to_testcase():
    """last_with_stress 不得套到 testcase，否则确认卡 ack 会被 TaskCreate 拒绝。"""
    plan = plan_from_slash(parse_slash("/testcase"), prefs={"last_with_stress": True}, attachments=[])
    apply_prefs_suggestions(plan, {"last_with_stress": True, "last_kind": "benchmark"})
    assert plan.slots["filled"].get("with_stress") is not True
    react = ReactArtifact()
    spec = build_proposed_spec(plan, react, slash_fill_first=False)
    assert spec is None


def test_prefs_stress_still_applies_to_benchmark():
    plan = l0_plan("帮我评一下")
    apply_prefs_suggestions(plan, {"last_with_stress": True})
    assert plan.slots["filled"].get("with_stress") is True


def test_compact_aborted_before_model_does_not_write():
    """/stop 或墙钟已置位时 compact 不得改列。"""
    stop = threading.Event()
    stop.set()
    session = AgentSession(id="s1", user_id="u1", title="t")
    assert run_compact(_FakeDb(), session, stop=stop) is None
    assert session.compact_summary is None


def test_run_plan_slash_keeps_pref_thoughts():
    """TC-14 / HAR-PLAN-06：偏好建议必须挂到 plan.pref_thoughts，供 Harness 发思考卡。"""
    plan = run_plan(
        _FakeDb(),
        text="/benchmark",
        parsed=parse_slash("/benchmark"),
        history=[],
        prefs={"last_profile_ids": ["p-last"], "last_dataset_id": "d-last"},
        attachments=[],
        budget=TurnBudget(),
    )
    assert plan.intent == "chat"
    assert plan.pref_thoughts == []


def test_prefs_suggestions_return_reuse_copy():
    plan = plan_from_slash(parse_slash("/benchmark"), prefs={}, attachments=[])
    thoughts = apply_prefs_suggestions(plan, {"last_profile_ids": ["p1"], "last_dataset_id": "d1"})
    assert thoughts == []


def test_gates_occupied_forbids_second_card():
    """TC-05：会话有 running 任务时禁止再发 confirm。"""

    class _FakeTask:
        kind = "benchmark"
        status = "running"
        id = "t-run"

    class _OccupiedQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return _FakeTask()

        def all(self):
            return []

    class _OccupiedDb:
        def query(self, *_args, **_kwargs):
            return _OccupiedQuery()

    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": []},
        tools_needed=["model.list", "dataset.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="slash",
    )
    react = ReactArtifact(
        proposed_spec={
            "kind": "benchmark",
            "profile_ids": ["p-real"],
            "dataset_id": "d-real",
            "run": {"sample_size": 1000},
            "with_stress": False,
        },
        known_ids=["p-real", "d-real"],
    )
    session = AgentSession(id="s1", user_id="u1", title="t")
    artifact = run_gates(_OccupiedDb(), session=session, plan=plan, react=react)
    assert artifact.verdict == "reject"
    # 业务任务工具已经移除，门禁会先拒绝该无效的业务执行计划。
    assert artifact.error_code == ErrorCode.VALIDATION.value
    assert "model.list" in artifact.reasons[0]
    assert artifact.spec is None


def test_turn_budget_hard_cap_four():
    """TC-09：单回合模型调用硬顶 4 次。"""
    budget = TurnBudget(cap=MAX_MODEL_CALLS)
    assert all(budget.consume() for _ in range(MAX_MODEL_CALLS))
    assert budget.consume() is False
    assert budget.remaining() == 0


def test_run_plan_greeting_skips_planner_for_cot(monkeypatch):
    """问候不打独立规划模型；CoT 由后续 ReAct 流式思考链一步一步出。"""

    def _boom(*_a, **_k):
        raise AssertionError("自然语言不得打独立规划模型")

    monkeypatch.setattr("app.agent.plan._call_plan_model", _boom)
    budget = TurnBudget()
    started = time.perf_counter()
    plan = run_plan(
        _FakeDb(),
        text="你好",
        parsed=parse_slash("你好"),
        history=[],
        prefs={},
        attachments=[],
        budget=budget,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert plan.intent == "chat"
    assert plan.loop == "react"
    assert plan.delivery == "text"
    assert plan.used_model is False
    assert plan.source == "react"
    assert budget.used == 0
    # 规划阶段不得再打模型；本地种子应在几十毫秒内完成。
    assert elapsed_ms < 50


_PLAN_JSON = {
    "intent": "chat",
    "skill_id": None,
    "slots": {"filled": {}, "missing": []},
    "tools_needed": [],
    "delivery": "text",
    "budget": {"max_tool_rounds": 0},
    "notes": "规划：问候。",
    "complexity": "low",
    "loop": "chat",
}


def test_call_plan_model_streams_when_reasoning_callback(monkeypatch):
    """规划有思考回调时必须流式，推理增量立即回调，不得整包空等。"""
    chunks: list[str] = []

    def _fake_stream(_db, _system, _user, **kwargs):
        cb = kwargs.get("on_reasoning")
        if cb:
            cb("先判断是闲聊")
        return AgentJsonStreamResult(
            text=json.dumps(_PLAN_JSON, ensure_ascii=False),
            reasoning="先判断是闲聊",
            latency_ms=11,
        )

    monkeypatch.setattr("app.llm.stream_agent_json", _fake_stream)
    monkeypatch.setattr(
        "app.llm.call_agent_model_detailed",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("有思考回调时不得走非流式规划")),
    )
    raw, latency = _call_plan_model(
        _FakeDb(),
        {"text": "你好", "command": "", "args": "", "history": [], "prefs": {}, "attachments": []},
        extra_system="",
        budget=TurnBudget(),
        cancel=CancellationToken(turn_id="t-plan-stream"),
        trace=TraceContext.for_turn(),
        on_reasoning=chunks.append,
    )
    assert chunks == ["先判断是闲聊"]
    assert raw["loop"] == "chat"
    assert latency == 11


def test_call_plan_model_nonstream_without_callback(monkeypatch):
    """无思考回调时保持非流式，便于单测夹具。"""

    class _Result:
        text = json.dumps(_PLAN_JSON, ensure_ascii=False)
        latency_ms = 6

    monkeypatch.setattr("app.llm.call_agent_model_detailed", lambda *_a, **_k: _Result())
    monkeypatch.setattr(
        "app.llm.stream_agent_json",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("无回调不应走流式规划")),
    )
    raw, latency = _call_plan_model(
        _FakeDb(),
        {"text": "你好", "command": "", "args": "", "history": [], "prefs": {}, "attachments": []},
        extra_system="",
        budget=TurnBudget(),
    )
    assert raw["intent"] == "chat"
    assert latency == 6


def test_run_replan_propagates_turn_cancelled(monkeypatch):
    """补规划读流取消不得被当成 JSON 失败改判 clarify。"""

    def _boom(*_a, **_k):
        raise TurnCancelled("disconnect")

    monkeypatch.setattr("app.agent.plan._call_plan_model", _boom)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["dataset_id"]},
        tools_needed=["dataset.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    with pytest.raises(TurnCancelled):
        run_replan(
            _FakeDb(),
            text="评测",
            parsed=parse_slash("评测"),
            history=[],
            prefs={},
            attachments=[],
            budget=TurnBudget(),
            plan=plan,
            observations=[],
        )


def test_run_plan_offtopic_skips_planner_not_eval_defaults(monkeypatch):
    """离题请求不打规划模型，也不得被 L0 套成 benchmark + list 工具。"""

    def _boom(*_a, **_k):
        raise AssertionError("自然语言不得打独立规划模型")

    monkeypatch.setattr("app.agent.plan._call_plan_model", _boom)
    budget = TurnBudget()
    plan = run_plan(
        _FakeDb(),
        text="帮我生成一首轻盈的音乐",
        parsed=parse_slash("帮我生成一首轻盈的音乐"),
        history=[],
        prefs={},
        attachments=[],
        budget=budget,
    )
    assert classify_intent_l0("帮我生成一首轻盈的音乐")[0] == "chat"
    assert plan.intent == "chat"
    assert plan.skill_id is None
    assert plan.delivery == "text"
    assert plan.source == "react"
    assert plan.loop == "react"
    assert plan.tools_needed == []
    assert budget.used == 0


def test_run_plan_inspect_skips_planner_no_business_tools(monkeypatch):
    """列出协议档不打规划模型，也不再注入已下线的业务 list 工具。"""

    def _boom(*_a, **_k):
        raise AssertionError("自然语言不得打独立规划模型")

    monkeypatch.setattr("app.agent.plan._call_plan_model", _boom)
    budget = TurnBudget()
    plan = run_plan(
        _FakeDb(),
        text="列出协议档",
        parsed=parse_slash("列出协议档"),
        history=[],
        prefs={"last_profile_ids": ["p-old"], "last_dataset_id": "ds-old"},
        attachments=[],
        budget=budget,
    )
    assert plan.intent == "chat"
    assert plan.loop == "react"
    assert plan.skill_id is None
    assert plan.tools_needed == []
    assert plan.pref_thoughts == []


def test_run_plan_portrait_injects_image_without_planner(monkeypatch):
    """人像摄影由 inject 挂生图工具；不打规划模型，不得沿用评测偏好。"""
    text = "帮我生成一张一张竖幅户外人像摄影，整体从上到下呈现温暖的午后街景氛围"

    def _boom(*_a, **_k):
        raise AssertionError("自然语言不得打独立规划模型")

    monkeypatch.setattr("app.agent.plan._call_plan_model", _boom)
    budget = TurnBudget()
    plan = run_plan(
        _FakeDb(),
        text=text,
        parsed=parse_slash(text),
        history=[],
        prefs={"last_profile_ids": ["p-old"], "last_dataset_id": "ds-old"},
        attachments=[],
        budget=budget,
    )
    assert plan.intent == "chat"
    assert plan.loop == "react"
    assert plan.skill_id is None
    assert plan.delivery == "text"
    assert plan.source == "react"
    assert plan.tools_needed == ["image.generate"]
    assert plan.pref_thoughts == []
    assert resolve_turn_mode(text=text, parsed=parse_slash(text), plan=plan) is TurnMode.REACT_ONLY
    assert should_emit_stage_thoughts(plan.intent, None, TurnMode.REACT_ONLY) is False



def test_maybe_model_check_skips_chat_text(monkeypatch):
    """闲聊 delivery=text 只走规则门禁，不再串行核对上游。"""

    def _boom(*_args, **_kwargs):
        raise AssertionError("闲聊不应调用核对模型")

    monkeypatch.setattr("app.llm.call_agent_model_detailed", _boom)
    budget = TurnBudget()
    plan = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=[],
        delivery="text",
        budget={"max_tool_rounds": 0},
        notes="规划：闲聊",
        source="l0",
    )
    out = maybe_model_check(
        _FakeDb(),
        ReflectArtifact(verdict="pass", reasons=["确认没有 create"]),
        plan=plan,
        text="你好",
        budget=budget,
    )
    assert out.verdict == "pass"
    assert budget.used == 0


def test_maybe_model_check_skips_when_rules_failed():
    """规则失败立即 clarify/reject，不得再调模型放行。"""
    budget = TurnBudget()
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": []},
        tools_needed=[],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    out = maybe_model_check(
        _FakeDb(),
        ReflectArtifact(verdict="reject", reasons=["禁止长工具"]),
        plan=plan,
        text="评测",
        budget=budget,
    )
    assert out.verdict == "reject"
    assert budget.used == 0


def test_maybe_model_check_sends_observations(monkeypatch):
    """HAR-ACT-01：核对调用带上观察摘要，不占 20 条窗口。"""
    captured: dict = {}

    class _Result:
        text = '{"verdict":"pass","reasons":[],"spec":null}'
        latency_ms = 4

    def _fake_call(_db, _system, user_blob, **_kwargs):
        captured["user"] = user_blob
        return _Result()

    monkeypatch.setattr("app.llm.call_agent_model_detailed", _fake_call)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": []},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    budget = TurnBudget()
    maybe_model_check(
        _FakeDb(),
        ReflectArtifact(verdict="pass", reasons=["ok"], spec={"kind": "benchmark"}),
        plan=plan,
        text="评测",
        budget=budget,
        observations=[{"name": "model.list", "ok": True, "data_summary": {"ids": ["p1"]}}],
    )
    assert "model.list" in captured["user"]
    assert budget.used == 1


def test_rag_slash_is_removed():
    """RAG 业务斜杠已移除，不能再作为系统命令校验。"""
    assert is_unknown_slash(parse_slash("/rag")) is True


def test_failed_list_does_not_fill_hallucinated_ids():
    """TC-17：工具失败不得用幻觉 ID 填槽。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark", "dataset_id": "d-fake"}, "missing": ["dataset_id"]},
        tools_needed=["dataset.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    react = ReactArtifact(
        observations=[
            {
                "name": "dataset.list",
                "ok": False,
                "latency_ms": 1,
                "data_summary": {"error": "该能力未启用"},
            }
        ],
        known_ids=[],
    )
    spec = build_proposed_spec(plan, react, slash_fill_first=False)
    assert spec is not None
    assert spec.get("dataset_id") != "d-fake"
    assert "dataset_id" not in spec or spec.get("dataset_id") is None


def test_merge_replan_only_queues_unexecuted_tools():
    """补规划只追加尚未执行的工具，不得开第二轮补规划。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["dataset_id"]},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    extra = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["dataset_id"]},
        tools_needed=["model.list", "dataset.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="补规划：再列出数据集",
        source="replan",
    )
    plan, extra_tools = merge_replan(plan, extra, executed_tool_names=["model.list"])
    assert extra_tools == []
    assert plan.delivery == "confirm"


def test_merge_replan_text_delivery_becomes_clarify():
    """补规划不得把下单回合改成 text，否则会误走闲聊交付。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["dataset_id"]},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    extra = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=[],
        delivery="text",
        budget={"max_tool_rounds": 0},
        notes="随便聊聊",
        source="replan",
    )
    plan, extra_tools = merge_replan(plan, extra, executed_tool_names=["model.list"])
    assert plan.delivery == "clarify"
    assert extra_tools == []


def test_merge_replan_drops_long_and_write_tools_from_queue():
    """长工具留给 G4 拒绝；不得在补规划续跑里执行 task.create / benchmark.run。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["dataset_id"]},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    extra = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["dataset_id"]},
        tools_needed=["model.list", "dataset.list", "benchmark.run", "task.create"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="补规划",
        source="replan",
    )
    plan, extra_tools = merge_replan(plan, extra, executed_tool_names=["model.list"])
    assert extra_tools == []
    assert "benchmark.run" in plan.tools_needed


def test_stale_pref_notes_are_deduped():
    """同一轮多次组 spec 不得重复发「上次的协议档已删除」。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark", "profile_ids": ["gone"]}, "missing": ["profile_ids"]},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    react = ReactArtifact(
        observations=[
            {
                "name": "model.list",
                "ok": True,
                "latency_ms": 1,
                "data_summary": {"count": 1, "ids": ["p1"], "names": ["a"]},
            }
        ],
        known_ids=["p1"],
    )
    build_proposed_spec(plan, react, slash_fill_first=False)
    build_proposed_spec(plan, react, slash_fill_first=False)
    assert react.pref_stale_notes.count("上次的协议档已删除") == 1


def test_run_react_continuation_respects_rounds_used(monkeypatch):
    """补规划续跑必须计入已消耗轮次，不得突破硬顶。"""
    calls: list[str] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "tool_call":
            calls.append(str(payload.get("name")))
        return 1

    def _fake_exec(_db, name, _arguments, *, user_id, allow_create=False):
        return True, {"items": []}, None, 1

    monkeypatch.setattr("app.agent.react.execute_short_tool", _fake_exec)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids", "dataset_id"]},
        tools_needed=["model.list"] * 4,
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    react = asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            **_turn_ctx(),
        )
    )
    assert calls == []
    assert react.rounds_used == 0
    asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            prior=react,
            extra_tools=["dataset.list"],
            **_turn_ctx(),
        )
    )
    assert calls == []


def test_run_react_long_tool_handoff_without_execute():
    """规划若误点长工具，只发思考卡移交 Worker，不得 execute 也不得打断整轮。"""
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return len(events)

    plan = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=["testcase.generate"],
        delivery="text",
        budget={"max_tool_rounds": 1},
        notes="规划：闲聊",
        source="llm",
    )
    react = asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            text="帮我生成一首轻盈的音乐",
            **_turn_ctx(),
        )
    )
    assert events[0][0] == "thought"
    assert events[0][1].get("stage") == "react"
    assert "长任务" in (events[0][1].get("text") or "")
    assert all(ev[0] != "tool_call" for ev in events)
    assert react.observations == []


def test_run_replan_without_budget_clarifies():
    """补规划计入 4 次硬顶，达顶改判 clarify。"""
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids"]},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    extra = run_replan(
        _FakeDb(),
        text="帮我评一下",
        parsed=parse_slash("帮我评一下"),
        history=[],
        prefs={},
        attachments=[],
        budget=TurnBudget(used=4, cap=4),
        plan=plan,
        observations=[{"name": "model.list", "ok": True}],
    )
    assert extra.delivery == "clarify"
    assert extra.source == "replan"


def test_run_react_stops_at_five_rounds(monkeypatch):
    """TC-08：工具轮次硬顶 5。"""
    calls: list[str] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "tool_call":
            calls.append(str(payload.get("name")))
        return 1

    def _fake_exec(_db, name, _arguments, *, user_id, allow_create=False):
        return True, {"items": []}, None, 1

    monkeypatch.setattr("app.agent.react.execute_short_tool", _fake_exec)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids", "dataset_id"]},
        tools_needed=["model.list"] * 6,
        delivery="confirm",
        budget={"max_tool_rounds": 99},
        notes="规划",
        source="llm",
    )
    asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            **_turn_ctx(),
        )
    )
    assert calls == []


def test_parse_mcp_step_keeps_long_tool_and_drops_writes():
    """长工具名留给循环移交；task.create 不得进入执行。"""
    long_step = parse_mcp_step({"thought": "去跑评测", "tool": "benchmark.run", "arguments": {}, "done": False})
    assert long_step.tool == "benchmark.run"
    write_step = parse_mcp_step({"tool": "task.create", "arguments": {"kind": "benchmark"}, "done": False})
    assert write_step.tool is None
    assert write_step.done is True


def test_run_react_mcp_loop_executes_one_tool_per_round(monkeypatch):
    """MCP ReAct：每轮 JSON 只执行 1 个短工具，多轮后留下 reply。"""
    rounds = {"n": 0}
    calls: list[str] = []
    thoughts: list[str] = []

    async def _fake_step(**_kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return McpStep(thought="先列出协议档", tool="model.list", arguments={}, done=False, reply="")
        if rounds["n"] == 2:
            return McpStep(thought="再列出数据集", tool="dataset.list", arguments={}, done=False, reply="")
        return McpStep(thought="观察已够", tool=None, arguments={}, done=True, reply="当前共 1 个协议档。")

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "tool_call":
            calls.append(str(payload.get("name")))
        if event == "thought" and payload.get("stage") == "react":
            thoughts.append(str(payload.get("text") or ""))
        return 1

    def _fake_exec(_db, name, _arguments, *, user_id, allow_create=False):
        if name == "model.list":
            return True, {"items": [{"id": "p1", "name": "a"}]}, None, 1
        return True, {"items": [{"id": "d1", "name": "ds"}]}, None, 1

    monkeypatch.setattr("app.agent.react._stream_mcp_step", _fake_step)
    monkeypatch.setattr("app.agent.react.execute_short_tool", _fake_exec)
    plan = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=[],
        delivery="text",
        budget={"max_tool_rounds": 4},
        notes="规划：闲聊",
        source="l0",
    )
    react = asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            use_llm=True,
            stop=threading.Event(),
            **_turn_ctx(),
        )
    )
    assert calls == ["model.list", "dataset.list"]
    assert thoughts[:2] == ["先列出协议档", "再列出数据集"]
    assert react.used_llm is True
    assert react.reply_text == "当前共 1 个协议档。"
    assert [obs["name"] for obs in react.observations] == ["model.list", "dataset.list"]
    assert react.rounds_used == 2


def test_run_react_long_tool_does_not_execute(monkeypatch):
    """长任务只发思考卡移交，不得在对话进程 execute_short_tool。"""
    calls: list[str] = []

    async def _fake_step(**_kwargs):
        return McpStep(thought="去跑评测", tool="benchmark.run", arguments={}, done=False, reply="")

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "tool_call":
            calls.append(str(payload.get("name")))
        return 1

    def _fake_exec(*_args, **_kwargs):
        raise AssertionError("长任务不得在 ReAct 循环内执行")

    monkeypatch.setattr("app.agent.react._stream_mcp_step", _fake_step)
    monkeypatch.setattr("app.agent.react.execute_short_tool", _fake_exec)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark", "profile_ids": ["p1"], "dataset_id": "d1"}, "missing": []},
        tools_needed=[],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    react = asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            use_llm=True,
            stop=threading.Event(),
            **_turn_ctx(),
        )
    )
    assert calls == []
    assert react.used_llm is True
    assert react.observations == []


def test_run_react_llm_unavailable_falls_back_to_tools_needed(monkeypatch):
    """模型不可用时仍按 tools_needed 串行，保证斜杠下单不空转。"""
    calls: list[str] = []

    async def _fail(*_args, **_kwargs):
        raise AppError(ErrorCode.VALIDATION, "未配置 Agent 协议档，请先到协议档页指定")

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "tool_call":
            calls.append(str(payload.get("name")))
        return 1

    def _fake_exec(_db, name, _arguments, *, user_id, allow_create=False):
        return True, {"items": [{"id": "p1", "name": "a"}]}, None, 1

    monkeypatch.setattr("app.agent.react._stream_mcp_step", _fail)
    monkeypatch.setattr("app.agent.react.execute_short_tool", _fake_exec)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids"]},
        tools_needed=["model.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="slash",
    )
    react = asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=True,
            use_llm=True,
            stop=threading.Event(),
            **_turn_ctx(),
        )
    )
    assert calls == []
    assert react.used_llm is False
    # 模型不可用时也不能回退执行已删除的业务资产查询工具。
    assert react.proposed_spec and react.proposed_spec.get("profile_ids") is None


def test_run_react_llm_stop_does_not_drain_tools_needed(monkeypatch):
    """模型已 done 时不得再把 tools_needed 当固定剧本跑完。"""
    calls: list[str] = []

    async def _fake_step(**_kwargs):
        return McpStep(
            thought="用户在问概念，不必列资产",
            tool=None,
            arguments={},
            done=True,
            reply="评测需要协议档和数据集，你想对比哪几个模型？",
        )

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        if event == "tool_call":
            calls.append(str(payload.get("name")))
        return 1

    def _fake_exec(*_args, **_kwargs):
        raise AssertionError("模型停止后不应再执行规划清单")

    monkeypatch.setattr("app.agent.react._stream_mcp_step", _fake_step)
    monkeypatch.setattr("app.agent.react.execute_short_tool", _fake_exec)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids", "dataset_id"]},
        tools_needed=["model.list", "dataset.list"],
        delivery="confirm",
        budget={"max_tool_rounds": 4},
        notes="规划",
        source="llm",
    )
    react = asyncio.run(
        run_react(
            _FakeDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            use_llm=True,
            stop=threading.Event(),
            **_turn_ctx(),
        )
    )
    assert calls == []
    assert react.used_llm is True
    assert react.reply_text.startswith("评测需要协议档")


def test_ack_illegal_dataset_keeps_pending_confirm():
    """TC-19 / TC-20b：ack patch 手填已删除 ID → error 指出字段，卡保留。"""

    class _Row:
        def __init__(self, row_id: str):
            self.id = row_id

    class _AckQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            if self.model is ProtocolProfile:
                return [_Row("p1")]
            return []

        def first(self):
            if self.model is Dataset:
                return None
            if self.model is Task:
                return None
            return None

    class _AckDb:
        def query(self, model):
            return _AckQuery(model)

        def add(self, *_args, **_kwargs):
            return None

        def commit(self):
            return None

        def flush(self):
            return None

    class _User:
        id = "u1"

    session = AgentSession(id="s1", user_id="u1", title="t")
    session.pending_confirm = {
        "kind": "benchmark",
        "profile_ids": ["p1"],
        "dataset_id": "d-old",
        "run": {
            "sample_size": 1000,
            "concurrency": 4,
            "timeout_s": 60,
            "retry": 1,
            "temperature": 0,
            "max_tokens": 1024,
            "system_prompt": "",
            "k": 5,
            "use_judge": False,
        },
        "with_stress": False,
    }
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return 1

    asyncio.run(
        handle_confirm_ack(
            _AckDb(),
            session=session,
            user=_User(),
            ok=True,
            patch={"dataset_id": "d-gone"},
            emit=_emit,
        )
    )
    assert session.pending_confirm is not None
    errors = [item for item in events if item[0] == "error"]
    assert errors
    assert "dataset_id" in errors[0][1]["message"]
    assert errors[0][1]["code"] == ErrorCode.VALIDATION.value


def test_ack_patch_kind_rag_rejected_keeps_pending_confirm():
    """确认卡 patch 改成 rag 必须被拒，与规划门禁一致，卡保留。"""

    class _AckDb:
        def query(self, model):
            class _Q:
                def filter(self, *args, **kwargs):
                    return self

                def with_for_update(self):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return _Q()

        def add(self, *_args, **_kwargs):
            return None

        def commit(self):
            return None

        def flush(self):
            return None

    class _User:
        id = "u1"

    session = AgentSession(id="s1", user_id="u1", title="t")
    session.pending_confirm = {
        "kind": "benchmark",
        "profile_ids": ["p1"],
        "dataset_id": "d1",
        "run": {
            "sample_size": 1000,
            "concurrency": 4,
            "timeout_s": 60,
            "retry": 1,
            "temperature": 0,
            "max_tokens": 1024,
            "system_prompt": "",
            "k": 5,
            "use_judge": False,
        },
        "with_stress": False,
    }
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return 1

    asyncio.run(
        handle_confirm_ack(
            _AckDb(),
            session=session,
            user=_User(),
            ok=True,
            patch={"kind": "rag", "kb_id": "kb1", "gold_qa_id": "g1"},
            emit=_emit,
        )
    )
    assert session.pending_confirm is not None
    errors = [item for item in events if item[0] == "error"]
    assert errors
    assert errors[0][1]["code"] == ErrorCode.VALIDATION.value
    assert "知识库" in errors[0][1]["message"]


def test_confirm_ack_without_card_does_not_fake_cancel():
    """没有待确认卡时 ok=false 不得写取消交付句。"""

    class _AckDb:
        def query(self, *_args, **_kwargs):
            class _Q:
                def filter(self, *args, **kwargs):
                    return self

                def with_for_update(self):
                    return self

                def first(self):
                    return None

            return _Q()

        def commit(self):
            raise AssertionError("无待确认卡不得 commit")

    class _User:
        id = "u1"

    session = AgentSession(id="s1", user_id="u1", title="t")
    session.pending_confirm = None
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return 1

    asyncio.run(
        handle_confirm_ack(
            _AckDb(),
            session=session,
            user=_User(),
            ok=False,
            patch=None,
            emit=_emit,
        )
    )
    assert session.pending_confirm is None
    assert events[0][0] == "error"
    assert events[0][1]["code"] == ErrorCode.VALIDATION.value
    assert "没有待确认" in events[0][1]["message"]
    assert not any(item[0] == "confirm_ack" for item in events)


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _FakeDb:
    def query(self, *_args, **_kwargs):
        return _FakeQuery()


class _CancelQuery:
    """返回指定任务的取消链路查询桩。"""

    def __init__(self, task: Task | None):
        self.task = task
        self.locked = False

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.task

    def with_for_update(self):
        self.locked = True
        return self


class _CancelDb:
    """覆盖 WS 取消分支所需的最小事务观测。"""

    def __init__(self, task: Task | None):
        self.query_result = _CancelQuery(task)
        self.added: list = []
        self.commit_calls = 0

    def query(self, *_args, **_kwargs):
        return self.query_result

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commit_calls += 1


def _cancel_task(status: str = "running", creator: str = "u-owner", session_id: str = "s-cancel") -> Task:
    """构造不落库的 WS 取消任务。"""
    return Task(
        id="t-cancel",
        kind="benchmark",
        status=status,
        session_id=session_id,
        created_by=creator,
        config={},
        progress={"done": 1, "total": 10},
        result={},
    )


def test_ws_cancel_by_creator_writes_timeline_and_confirmation():
    """WS 取消与 REST 同样写审计、时间线，并回传可关联任务的确认事件。"""
    task = _cancel_task()
    db = _CancelDb(task)
    events: list[tuple[str, dict, str | None]] = []

    async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
        events.append((event, payload, task_id))
        return len(events)

    asyncio.run(
        handle_cancel_task(
            db,
            session=AgentSession(id="s-cancel", user_id="u-owner", title="取消测试"),
            user=User(id="u-owner", username="owner"),
            task_id=task.id,
            emit=emit,
        )
    )

    assert task.status == "cancelled"
    assert task.cancel_requested_at == task.finished_at
    assert task.progress["message"] == "任务已取消"
    added_types = {type(item).__name__ for item in db.added}
    assert {"TaskEvent", "AuditLog", "Message"} <= added_types
    timeline = next(item for item in db.added if type(item).__name__ == "TaskEvent")
    assert timeline.event == "cancelled"
    assert timeline.payload == {"status": "cancelled"}
    assert ("tool_call", {"name": "task.cancel", "arguments": {"task_id": task.id}}, task.id) in events
    assert any(
        event == "tool_result" and payload["ok"] is True and payload["data"]["task_id"] == task.id and event_task_id == task.id
        for event, payload, event_task_id in events
    )
    assert any(event == "thought" and event_task_id == task.id for event, _payload, event_task_id in events)
    assert db.commit_calls == 2
    assert db.query_result.locked is True


def test_ws_cancel_by_non_creator_is_unauthorized_without_writes():
    """WS 入口不得用 NOT_FOUND 隐藏已有任务，也不能写入取消状态。"""
    task = _cancel_task(creator="u-owner")
    db = _CancelDb(task)
    events: list[tuple[str, dict, str | None]] = []

    async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
        events.append((event, payload, task_id))
        return len(events)

    asyncio.run(
        handle_cancel_task(
            db,
            session=AgentSession(id="s-cancel", user_id="u-other", title="取消测试"),
            user=User(id="u-other", username="other"),
            task_id=task.id,
            emit=emit,
        )
    )

    assert events == [("error", {"code": ErrorCode.UNAUTHORIZED.value, "message": "没有权限做这件事"}, task.id)]
    assert task.status == "running"
    assert task.cancel_requested_at is None
    assert db.added == []
    assert db.commit_calls == 0


@pytest.mark.parametrize("status", ["succeeded", "cancelled"])
def test_ws_cancel_terminal_task_is_rejected_without_writes(status: str):
    """已结束任务拒绝重复取消，不能追加审计或时间线噪声。"""
    task = _cancel_task(status=status)
    db = _CancelDb(task)
    events: list[tuple[str, dict, str | None]] = []

    async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
        events.append((event, payload, task_id))
        return len(events)

    asyncio.run(
        handle_cancel_task(
            db,
            session=AgentSession(id="s-cancel", user_id="u-owner", title="取消测试"),
            user=User(id="u-owner", username="owner"),
            task_id=task.id,
            emit=emit,
        )
    )

    assert events == [("error", {"code": ErrorCode.VALIDATION.value, "message": "任务已结束"}, task.id)]
    assert db.added == []
    assert db.commit_calls == 0


def test_ws_cancel_rejects_task_from_other_session():
    """WS 取消必须绑定当前会话，禁止把 B 会话任务的时间线写进 A。"""
    task = _cancel_task(session_id="s-other")
    db = _CancelDb(task)
    events: list[tuple[str, dict, str | None]] = []

    async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
        events.append((event, payload, task_id))
        return len(events)

    asyncio.run(
        handle_cancel_task(
            db,
            session=AgentSession(id="s-cancel", user_id="u-owner", title="取消测试"),
            user=User(id="u-owner", username="owner"),
            task_id=task.id,
            emit=emit,
        )
    )

    assert events == [
        ("error", {"code": ErrorCode.VALIDATION.value, "message": "只能取消当前会话中的任务"}, task.id)
    ]
    assert task.status == "running"
    assert db.added == []
    assert db.commit_calls == 0
