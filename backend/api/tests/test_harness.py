"""Harness 规划 / 复核 / 观察脱敏纯逻辑单测（不连库、不连上游）。"""

from __future__ import annotations

import pytest

from app.agent.defaults import HARD_MAX_TOOL_ROUNDS, is_long_tool
from app.agent.mcp_tools import redact_secrets, truncate_tool_data
from app.agent.plan import (
    PlanArtifact,
    classify_intent_l0,
    l0_plan,
    parse_json_object,
    plan_from_slash,
    sanitize_plan,
)
from app.agent.react import ReactArtifact
from app.agent.reflect import run_gates
from app.agent.slash import parse_slash
from app.errors import ErrorCode
from app.models import Session as AgentSession


def test_l0_chat_vs_benchmark_and_testcase():
    """L0：闲聊不胡乱下单；评测关键词进 benchmark；PRD 进 testcase。"""
    assert classify_intent_l0("介绍一下你")[0] == "chat"
    assert classify_intent_l0("你好")[0] == "chat"
    assert classify_intent_l0("今天天气如何")[0] == "chat"
    assert classify_intent_l0("对比两个模型的基准表现")[0] == "benchmark"
    assert classify_intent_l0("帮我评一下")[0] == "benchmark"
    assert classify_intent_l0("根据 PRD 生成测试用例")[0] == "testcase"
    assert classify_intent_l0("评测知识库召回效果")[0] == "rag"
    intent, stress = classify_intent_l0("先评后压 10 QPS")
    assert intent == "benchmark" and stress is True


def test_l0_plan_missing_slots_clarify_not_confirm():
    """D1：L0 缺槽时 delivery=clarify，仍进复核、不出假确认卡。"""
    plan = l0_plan("帮我评一下")
    assert plan.intent == "benchmark"
    assert "profile_ids" in plan.slots["missing"]
    assert plan.delivery == "clarify"
    assert "model.list" in plan.tools_needed


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


def test_parse_plan_json_rejects_plain_text():
    with pytest.raises(ValueError):
        parse_json_object("抱歉，我不明白你的意思。")


def test_slash_stress_never_kind_stress():
    """TC-07：/stress 的 intent 仍是质量任务，skill_id=skill-stress。"""
    parsed = parse_slash("/stress")
    plan = plan_from_slash(parsed, prefs={}, attachments=[])
    assert plan.intent == "benchmark"
    assert plan.skill_id == "skill-stress"
    assert plan.slots["filled"]["with_stress"] is True
    assert plan.slots["filled"]["kind"] == "benchmark"


def test_slash_testcase_missing_source():
    parsed = parse_slash("/testcase")
    plan = plan_from_slash(parsed, prefs={}, attachments=[])
    assert plan.intent == "testcase"
    assert plan.slots["missing"] == ["case_source"]
    assert plan.delivery == "clarify"


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
    assert artifact.verdict == "clarify"
    assert "资产不存在" in artifact.reasons[0]


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
