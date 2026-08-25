"""M7 跨层契约层单测（C-A1~C-A5）；不依赖 DB / WS。"""

import json

import pytest

from app.harness.contracts import (
    Observation,
    PlanArtifact,
    SkillHint,
    ToolCall,
    ToolResult,
    from_dict,
    make_event,
    to_dict,
    validate_plan_artifact,
)
from app.harness.contracts.events import NodeEventKind, is_persistent

# NodeEventKind 全集（对齐 API.md §4.3 持久化事件中图节点可产出子集；
# user_message/progress/report 允许产出但禁止与直产方重复 emit）
NODE_EVENT_KINDS = frozenset(
    {
        "user_message",
        "thought",
        "tool_call",
        "tool_result",
        "confirm",
        "clarify",
        "plan",
        "progress",
        "report",
        "error",
        "assistant_message",
        "response.completed",
    }
)
# 收包循环/Worker 直产且**不入枚举**（confirm_ack 回执由收包循环直产）
NON_NODE_KINDS = frozenset({"confirm_ack"})


def test_node_event_kind_matches_api_persistent_events() -> None:
    """C-A1：NodeEventKind 与 API.md §4.3 持久化事件对齐（图节点产出子集）。"""
    assert set(NodeEventKind.__args__) == NODE_EVENT_KINDS
    # confirm_ack 由收包循环直连 emit，不进 NodeEventKind
    assert NON_NODE_KINDS.isdisjoint(NodeEventKind.__args__)


def test_make_event_validates_kind() -> None:
    """构造 NodeEvent 时非法 kind 抛 ValueError。"""
    with pytest.raises(ValueError):
        make_event("confirm_ack", {})  # type: ignore[arg-type]


def test_is_persistent_all_kinds() -> None:
    """全部 NodeEventKind 均为持久化事件（瞬态帧不进本枚举）。"""
    assert all(is_persistent(kind) for kind in NodeEventKind.__args__)


def test_node_event_json_serializable() -> None:
    """C-A3：NodeEvent 可 json.dumps。"""
    event = make_event("thought", {"text": "先判断", "stage": "plan"})
    dumped = json.dumps(event, ensure_ascii=False)
    assert "先判断" in dumped
    assert "event.v1" in dumped


def test_node_event_has_no_callable_or_websocket_fields() -> None:
    """C-A4：NodeEvent 不含 Callable/WebSocket 字段。"""
    event = make_event("assistant_message", {"text": "hi"})
    assert all(not callable(value) for value in event.values())
    assert not any(
        "WebSocket" in type(value).__name__ or "Callable" in type(value).__name__
        for value in event.values()
    )


def test_contracts_roundtrip_to_dict_from_dict() -> None:
    """C-A2：全部契约 to_dict → from_dict 往返相等。"""
    observation = Observation(
        tool="web_search",
        text="结果摘要",
        ok=True,
        truncated=True,
        source="message:abc",
    )
    tool_call = ToolCall(name="web_search", arguments={"query": "评测"})
    tool_result = ToolResult(name="web_search", ok=True, data={"hits": 3})
    plan = PlanArtifact(
        intent="运行基准评测",
        skill_id="skill-benchmark",
        slots={"dataset": "mmlu"},
        tools_needed=("benchmark.run",),
        delivery="confirm",
        budget={"model_calls": 2, "tool_turns": 1},
        allows_replan=True,
        notes="先评后压",
    )
    skill_hint = SkillHint(
        skill_id="skill-benchmark",
        name="基准评测",
        summary="执行大模型基准评测",
    )
    for contract in (observation, tool_call, tool_result, plan, skill_hint):
        restored = from_dict(type(contract), to_dict(contract))
        assert restored == contract


def test_contracts_json_serializable() -> None:
    """C-A3：所有契约 json.dumps 不抛 TypeError。"""
    observation = Observation(tool="web_search", text="摘要", ok=True)
    plan = PlanArtifact(
        intent="运行基准评测",
        skill_id="skill-benchmark",
        slots={"dataset": "mmlu"},
        tools_needed=("benchmark.run",),
        delivery="confirm",
        budget={"model_calls": 2, "tool_turns": 1},
        allows_replan=False,
    )
    for contract in (observation, plan):
        json.dumps(to_dict(contract))


def test_plan_artifact_schema_rejects_missing_fields() -> None:
    """C-A5：PlanArtifact schema 拒绝缺字段。"""
    data = to_dict(
        PlanArtifact(
            intent="运行基准评测",
            skill_id=None,
            slots={},
            tools_needed=(),
            delivery="chat",
            budget={},
            allows_replan=False,
        )
    )
    data.pop("intent")
    with pytest.raises(ValueError):
        validate_plan_artifact(data)


def test_plan_artifact_schema_rejects_extra_fields() -> None:
    """C-A5：PlanArtifact schema 拒绝多字段。"""
    data = to_dict(
        PlanArtifact(
            intent="运行基准评测",
            skill_id=None,
            slots={},
            tools_needed=(),
            delivery="chat",
            budget={},
            allows_replan=False,
        )
    )
    data["extra_field"] = True
    with pytest.raises(ValueError):
        validate_plan_artifact(data)


def test_observation_redacted_default_true() -> None:
    """Observation 默认已脱敏（FB-1 语义）。"""
    observation = Observation(tool="web_search", text="摘要", ok=True)
    assert observation.redacted is True
    assert observation.repair_hint == ""


def test_observation_from_dict_allows_missing_repair_hint() -> None:
    """新增 repair_hint 对旧投影缺省为空，不把旧检查点判非法。"""
    data = to_dict(Observation(tool="web_search", text="摘要", ok=True))
    data.pop("repair_hint")
    restored = from_dict(Observation, data)
    assert restored.repair_hint == ""
