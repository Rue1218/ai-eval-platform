"""F0/P1 原生工具装配测试（《Agent 原生工具装配方案》V0.2 §5 P1 验收①–⑥）。

覆盖：装配许可三态（主闸门 × profile 白名单，D5）、档级熔断摘除与冷却恢复、
工具选择交集收窄（下发集 ⊆ allowed∩registered∩native，D1/D4）、orchestrator
装配与双通道裁剪、tool_use 精确回退（无 tools 重发一次 + 审计日志，P1③）、
混合互斥（tool_calls 非空不解析 react，防双执行）、关闸字节级零 tools 回归
（验收⑤）、回合 usage 累计（turn_usage → assistant_message.turn_stats 审计
口径，R3-M1）。不依赖 WS/DB。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.taor_nodes import (
    _terminal_events,
    make_orchestrator_node,
    make_plan_node,
)
from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.context.assembly import select_tool_defs
from app.harness.execution.native_tools_policy import (
    native_tools_allowed,
    native_tools_breaker_reset,
    native_tools_breaker_snapshot,
    native_tools_report_failure,
    native_tools_report_success,
)
from app.harness.memory import GraphState, SerializableRequest
from app.harness.orchestration.agents import build_default_agent_registry
from app.harness.orchestration.budget import DEFAULT_BUDGET
from app.llm import ModelResponse, NativeToolCall

_U1 = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
_U2 = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}

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
_REACT_READ = (
    '{"thought":"读取报告","tool":"read","arguments":{"path":"result.md"},'
    '"done":false,"protocol":"react","version":"react.v1"}'
)


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


def _orch_state(**extra) -> GraphState:
    state: GraphState = {
        "request": _request("排查测试失败原因"),
        "engine": "agent",
        "router_confidence": 0.8,
        "router_reason": "探索排查意图（测试）",
        "plan": {
            "intent": "排查失败原因",
            "skill_id": None,
            "slots": {"steps": ["读取报告", "定位", "结论"]},
            "tools_needed": ("read",),
            "delivery": "chat",
            "budget": {},
            "allows_replan": False,
            "notes": "",
        },
        "agent_id": "worker.diagnose",
        "allowed_tools": ("read", "TaskGet", "TaskList", "web_search"),
        "budget": dict(DEFAULT_BUDGET),
        "plan_step_index": 0,
        "observations": [],
    }
    state.update(extra)
    return state


class _ScriptedGateway:
    """按序号返回预置 ModelResponse；超出序列抛 AssertionError（断言调用圈数）。"""

    def __init__(self, *responses: ModelResponse):
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[object] = []

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        if self.calls >= len(self._responses):
            raise AssertionError(f"模型调用超出脚本：第 {self.calls} 次")
        self.requests.append(request)
        response = self._responses[self.calls]
        self.calls += 1
        return response


def _default_tool_registry() -> object:
    from app.harness.execution.registry import build_default_registry

    return build_default_registry()


def _make_orch(gateway: _ScriptedGateway):
    agents = build_default_agent_registry()
    return make_orchestrator_node(gateway, agents, _default_tool_registry())


@pytest.fixture(autouse=True)
def _reset_breaker():
    native_tools_breaker_reset()
    yield
    native_tools_breaker_reset()


# ─── 1. 装配许可三态（D5：主闸门 × per-profile 白名单）───


def test_policy_main_switch_off_denies(monkeypatch) -> None:
    monkeypatch.setattr(settings, "agent_native_tools_enabled", False)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    assert native_tools_allowed("p-1") is False


def test_policy_allowlist_semantics(monkeypatch) -> None:
    """空清单 = 不开任何档；`*` = 全部（含空 profile）；显式清单仅命中。"""
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "")
    assert native_tools_allowed("p-1") is False

    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    assert native_tools_allowed("p-1") is True
    assert native_tools_allowed("") is True  # 直测无 run 上下文（configurable 缺失）

    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "p-1, p-2")
    assert native_tools_allowed("p-1") is True
    assert native_tools_allowed("p-2") is True
    assert native_tools_allowed("p-3") is False
    assert native_tools_allowed("") is False  # 无档可查时保守拒绝


# ─── 2. 档级熔断（P1 DoD②：连续失败摘除装配，冷却后恢复探测）───


def test_breaker_opens_after_threshold_and_recovers(monkeypatch, caplog) -> None:
    """用可控时钟验证熔断冷却边界，不依赖 Windows 的短时 sleep 精度。"""
    import logging

    from app.harness.execution import native_tools_policy

    clock = [100.0]
    monkeypatch.setattr(native_tools_policy, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    monkeypatch.setattr(settings, "circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "circuit_cooldown_s", 0.05)
    # halfopen 为 INFO 级，须提升捕获级别才能断言（生产由日志配置决定输出）
    caplog.set_level(logging.INFO, logger="ai-eval.agent")

    assert native_tools_allowed("p-1") is True
    native_tools_report_failure("p-1")
    assert native_tools_allowed("p-1") is True  # 1/2 未达阈值
    native_tools_report_failure("p-1")
    assert native_tools_allowed("p-1") is False  # open：摘除
    assert native_tools_breaker_snapshot().get("p-1", {}).get("open_until", 0) > 0
    # 熔断为可观测事件（冒烟据此验证档级摘除）
    assert any(
        record.getMessage().startswith("native_tools_breaker_open profile=p-1")
        for record in caplog.records
    )

    clock[0] += 0.06
    assert native_tools_allowed("p-1") is True  # 冷却到期：半开放行探测
    assert any(
        record.getMessage().startswith("native_tools_breaker_halfopen profile=p-1")
        for record in caplog.records
    )


def test_breaker_success_resets_failures(monkeypatch) -> None:
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    monkeypatch.setattr(settings, "circuit_failure_threshold", 3)
    native_tools_report_failure("p-1")
    native_tools_report_failure("p-1")
    native_tools_report_success("p-1")
    assert native_tools_allowed("p-1") is True
    native_tools_report_failure("p-1")
    native_tools_report_failure("p-1")
    assert native_tools_allowed("p-1") is True  # 成功清零后重新计数


def test_breaker_isolated_per_profile(monkeypatch) -> None:
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    monkeypatch.setattr(settings, "circuit_failure_threshold", 1)
    monkeypatch.setattr(settings, "circuit_cooldown_s", 60)
    native_tools_report_failure("p-1")
    assert native_tools_allowed("p-1") is False
    assert native_tools_allowed("p-2") is True  # 档间隔离


# ─── 3. 工具选择交集收窄（D1/D4：下发集 ⊆ allowed∩registered∩native）───


def test_select_tool_defs_only_intersects_allowed() -> None:
    """only 收窄：native 全量铺开与 tools_needed 并入均受 allowed 约束。"""
    registry = _default_tool_registry()
    defs = select_tool_defs(registry, mode="react", only=("read", "web_search"))
    names = [definition["name"] for definition in defs]
    assert set(names) == {"read", "web_search"}

    # tools_needed 点名视野外工具（bash）也被 only 剔除；native iter 内
    # 且在 only 内的工具不受 tools_needed 影响照常下发
    defs = select_tool_defs(
        registry, mode="react", tools_needed=("bash", "read"), only=("read", "web_search")
    )
    names = [definition["name"] for definition in defs]
    assert set(names) == {"read", "web_search"}
    assert "bash" not in names

    # 空 only → 空下发（调用方必须显式给 allowed_tools，不给则无工具）
    assert select_tool_defs(registry, mode="react", only=()) == []


def test_select_tool_defs_legacy_full_native_preserved() -> None:
    """向后兼容：不传 only 时维持全量 native ∪ tools_needed 旧语义（非白名单交集）。"""
    registry = _default_tool_registry()
    names = {definition["name"] for definition in select_tool_defs(registry, mode="react")}
    assert "read" in names and "bash" in names and "TaskCreate" in names
    assert select_tool_defs(registry, mode="chat") == []  # 非 react mode 恒空


# ─── 4. orchestrator 装配与回退（P1 DoD ①②③④）───


def test_orchestrator_gate_off_is_byte_level_legacy() -> None:
    """验收⑤：主闸门默认关 → 请求 tools 恒空、system 为 legacy 全量（现状零变化）。"""
    gateway = _ScriptedGateway(ModelResponse(text=_REACT_DONE, usage=_U1))
    update = _make_orch(gateway)(_orch_state())
    assert gateway.requests[0].tools == ()
    assert "可用工具：" in gateway.requests[0].system
    assert update["final_text"] and "样本量不足" in update["final_text"]


def test_orchestrator_native_assembly_and_defer(monkeypatch) -> None:
    """验收①②③④：开闸 → 首次请求含交集 tools + native system（无 schema 正文）；
    tool_use 出现 → 无 tools 重发一次（legacy system 恢复），回合正常收尾；usage 累计。"""
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    gateway = _ScriptedGateway(
        ModelResponse(
            text="",
            usage=_U1,
            tool_calls=(NativeToolCall(call_id="c1", name="read", arguments={"path": "r.md"}),),
        ),
        ModelResponse(text=_REACT_DONE, usage=_U2),
    )
    update = _make_orch(gateway)(_orch_state())
    first, second = gateway.requests

    # ① 下发集合非空且 ⊆ allowed_tools（真 registry native ∩ allowed）
    assert first.tools
    names = {tool["name"] for tool in first.tools}
    assert names <= {"read", "TaskGet", "TaskList", "web_search"}
    # 双通道裁剪：native system 无 schema 正文（定义经协议 tools 下发）
    assert "优先使用原生工具调用" in first.system
    assert "可用工具：" not in first.system

    # ③ 精确回退：第二次请求无 tools、system 恢复 legacy 全量（react JSON 可用）
    assert gateway.calls == 2
    assert second.tools == ()
    assert "可用工具：" in second.system
    # ④ 混合互斥：tool_calls 非空 → 直接回退，未把首个响应文本送 react 解析
    #（首个响应 text=""，若被解析将落入 3 次纠正而不是单次回退；calls==2 证明）

    # 回合正常收尾（H4：交 reflect 前落 final_text），usage 回合累计
    assert update["final_text"] and "样本量不足" in update["final_text"]
    assert update["turn_usage"]["total_tokens"] == _U1["total_tokens"] + _U2["total_tokens"]


def test_orchestrator_native_defer_then_react_act(monkeypatch) -> None:
    """回退后模型走文本 react Act：pending_tool.native=False（P1 不循环，文本路径执行）。"""
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    gateway = _ScriptedGateway(
        ModelResponse(
            text="",
            usage=_U1,
            tool_calls=(NativeToolCall(call_id="c1", name="web_search", arguments={"q": "x"}),),
        ),
        ModelResponse(text=_REACT_READ, usage=_U2),
    )
    update = _make_orch(gateway)(_orch_state())
    assert gateway.requests[1].tools == ()
    assert update["pending_tool"]["name"] == "read"
    assert update["pending_tool"]["native"] is False
    assert update["turn_usage"]["total_tokens"] == 45


def test_breaker_disarms_tools_across_turns(monkeypatch) -> None:
    """熔断集成：单回合带 tools 连续失败达阈值 → 后续回合请求无 tools（档级摘除）。"""
    monkeypatch.setattr(settings, "agent_native_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_native_tools_profile_ids", "*")
    monkeypatch.setattr(settings, "circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "circuit_cooldown_s", 60)

    class _FailingGateway:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
            self.requests.append(request)
            raise AppError(ErrorCode.UPSTREAM, "端点 400（模拟 tools 不支持）")

    failing = _FailingGateway()
    update = _make_orch(failing)(_orch_state())
    assert update["turn_failed"] is True
    # attempts ≤ 2（含首次共 3 次尝试的上限语义：首次 + 2 重试，每轮都带 tools）
    assert len(failing.requests) == 3
    assert all(request.tools for request in failing.requests)  # 失败均带 tools

    # 新一轮回合：breaker open → 装配摘除（请求无 tools，走 legacy 文本）
    gateway2 = _ScriptedGateway(ModelResponse(text=_REACT_DONE, usage=_U1))
    update2 = _make_orch(gateway2)(_orch_state())
    assert gateway2.requests[0].tools == ()
    assert "可用工具：" in gateway2.requests[0].system
    assert update2["final_text"]


# ─── 5. 回合 usage 累计（R3-M1：turn_stats 审计口径）───


def test_usage_accumulates_across_model_calls(monkeypatch) -> None:
    """plan 与 orchestrator 每次 invoke 的 usage 均并入 turn_usage（默认关闸亦审计）。"""
    monkeypatch.setattr(settings, "agent_native_tools_enabled", False)
    # plan 节点：一次调用
    plan_gateway = _ScriptedGateway(ModelResponse(text=_PLAN_OK, usage=_U1))
    plan_update = make_plan_node(plan_gateway)(_orch_state())
    assert plan_update["turn_usage"] == _U1

    # orchestrator 一次成功调用（无 tool_use、无解析重试）
    orch_gateway = _ScriptedGateway(ModelResponse(text=_REACT_DONE, usage=_U2))
    orch_update = _make_orch(orch_gateway)(_orch_state())
    assert orch_update["turn_usage"] == _U2


def test_terminal_events_carry_turn_stats_usage() -> None:
    """收尾 assistant_message 携带 turn_stats.usage（对齐 chat 路径 routing.py 口径）。"""
    state = _orch_state(turn_usage=_U1)
    events = _terminal_events(state, "完成", "stop")
    assistant = next(event for event in events if event["kind"] == "assistant_message")
    assert assistant["payload"]["turn_stats"] == {"usage": _U1}

    # 用量为空时不带 turn_stats（保持现状事件形状）
    events = _terminal_events(_orch_state(), "完成", "stop")
    assistant = next(event for event in events if event["kind"] == "assistant_message")
    assert "turn_stats" not in assistant["payload"]
