"""M7 跨层契约层单测（C-A1~C-A5）；不依赖 DB / WS。"""

import json

import pytest

from app.harness.contracts import (
    FailedStep,
    Observation,
    PlanArtifact,
    RejectedHypothesis,
    SkillHint,
    TaskSessionState,
    ToolCall,
    ToolResult,
    evolve_task_state,
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


def test_task_session_state_serialization_roundtrip() -> None:
    """TaskSessionState 契约：完整序列化与反序列化双向无损。"""
    state = TaskSessionState(
        goal="定位支付接口变慢原因",
        phase="verifying",
        completed_steps=("读取监控指标",),
        current_step="检查 v2.3.1 代码变更",
        next_actions=("查询第三方回调错误码",),
        failed_steps=(FailedStep(step="查日志", reason="无权限", repair_hint="改用只读账号"),),
        current_hypothesis="第三方支付回调超时可能导致变慢",
        confirmed_facts=("22:10 后 P95 升至 3.8s",),
        evidence=("file:attachments/metrics.csv",),
        rejected_hypotheses=(
            RejectedHypothesis(
                hypothesis="数据库慢查询",
                reason="慢查询日志未见异常",
                evidence_ref="mysql-slow.log",
            ),
        ),
        missing_info=("回调重试配置",),
        can_deliver=False,
    )
    raw = state.to_dict()
    # 必须 JSON 序列化安全
    assert json.dumps(raw)
    restored = TaskSessionState.from_dict(raw)
    assert restored.goal == "定位支付接口变慢原因"
    assert restored.phase == "verifying"
    assert restored.completed_steps == ("读取监控指标",)
    assert restored.current_step == "检查 v2.3.1 代码变更"
    assert restored.next_actions == ("查询第三方回调错误码",)
    assert len(restored.failed_steps) == 1
    assert restored.failed_steps[0].repair_hint == "改用只读账号"
    assert restored.rejected_hypotheses[0].hypothesis == "数据库慢查询"
    assert restored.can_deliver is False


def test_task_session_state_missing_info_forces_can_deliver_false() -> None:
    """不变式防线：只要存在未闭环的 missing_info，强制禁止标记 can_deliver=True。"""
    raw = {
        "goal": "分析系统瓶颈",
        "missing_info": ["压测 QPS 采样数据"],
        "can_deliver": True,  # 试图伪造完成
    }
    restored = TaskSessionState.from_dict(raw)
    assert restored.can_deliver is False


def test_evolve_task_state_advances_steps_and_records_evidence() -> None:
    """状态机演进：工具成功执行驱动步骤推进并记录证据。"""
    initial = TaskSessionState(
        goal="分析仓库代码",
        phase="exploring",
        completed_steps=(),
        current_step="读取目录结构",
        next_actions=("定位核心模块",),
        missing_info=("读取目录结构", "定位核心模块"),
        can_deliver=False,
    )
    obs = Observation(
        tool="read",
        text="src 目录下包含 api, worker 模块",
        ok=True,
        source="repo:root",
    )
    evolved = evolve_task_state(initial, [obs])
    assert "读取目录结构" in evolved.completed_steps
    assert evolved.current_step == "定位核心模块"
    assert "repo:root" in evolved.evidence
    assert any("read" in fact for fact in evolved.confirmed_facts)
    # 仍有定位核心模块未完成
    assert not evolved.can_deliver

    # 推进第二步
    obs2 = Observation(tool="read", text="已定位核心模块", ok=True, source="repo:src")
    evolved2 = evolve_task_state(evolved, [obs2])
    assert "定位核心模块" in evolved2.completed_steps
    assert evolved2.current_step == ""
    assert evolved2.can_deliver is True
    assert evolved2.phase == "converging"


def test_evolve_task_state_records_failures_and_rejects_hypothesis() -> None:
    """状态机演进：工具失败记录到 failed_steps 并证伪当前假设。"""
    initial = TaskSessionState(
        goal="排查故障",
        current_hypothesis="内存泄漏导致 OOM",
        missing_info=("检查 JVM 堆转储",),
        can_deliver=False,
    )
    obs = Observation(
        tool="bash",
        text="jstat 显示堆内存占用率仅 30%，非 OOM",
        ok=False,
        repair_hint="检查线程栈",
    )
    evolved = evolve_task_state(initial, [obs])
    assert len(evolved.failed_steps) == 1
    assert evolved.failed_steps[0].step == "bash"
    assert len(evolved.rejected_hypotheses) == 1
    assert evolved.rejected_hypotheses[0].hypothesis == "内存泄漏导致 OOM"
    assert not evolved.can_deliver

