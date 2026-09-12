"""H3 TAOR 主循环测试（开发计划 H3 阶段验收，批次 A）。

覆盖：AgentRegistry.discover 稳定性与 sandbox 排除、plan.v1 解析与 L0 降级、
orchestrator 守卫（非法工具/预算/重复读取/步数越界/协议重试上限）、
tools 包装预算扣减；图级：engine=agent 全链（plan → discover → orchestrator
⇄ tools → 收尾）单工具圈真实执行 read、Observation 只作模型输入、越权工具
fail-closed、ToolCard 事件无敏感值。不依赖 WS/DB。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent import LangGraphAgent
from app.agent.taor_nodes import (
    make_discover_node,
    make_orchestrator_node,
    make_plan_node,
    make_tools_node,
)
from app.harness.memory import GraphState, SerializableRequest
from app.harness.orchestration.agents import (
    AgentDef,
    AgentRegistry,
    build_default_agent_registry,
)
from app.harness.orchestration.budget import DEFAULT_BUDGET
from app.llm import ModelResponse
from tests._helpers import enable_hybrid_engine as _engine_on


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


def _state(text: str = "排查测试失败原因", **extra) -> GraphState:
    state: GraphState = {
        "request": _request(text),
        "engine": "agent",
        "router_confidence": 0.8,
        "router_reason": "探索排查意图（测试）",
    }
    state.update(extra)
    return state


_PLAN_OK = (
    '{"intent":"排查并定位测试报告失败原因","skill_id":null,'
    '"slots":{"steps":["读取报告","定位失败用例","给出结论"]},'
    '"tools_needed":["read"],"delivery":"chat",'
    '"budget":{"model_calls":6,"tool_turns":4},"allows_replan":false,'
    '"notes":"测试用计划","protocol":"plan","version":"plan.v1"}'
)


class _ScriptedGateway:
    """按调用序号返回预置文本；超出序列抛 AssertionError（断言模型调用圈数）。"""

    def __init__(self, *texts: str):
        self._texts = list(texts)
        self._errors: list = []
        self.calls = 0

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        self.calls += 1
        index = self.calls - 1
        if index < len(self._errors):
            raise self._errors[index]
        if index >= len(self._texts):
            raise AssertionError(f"模型调用超出脚本：第 {self.calls} 次")
        return ModelResponse(text=self._texts[index], usage={}, latency_ms=0)


def _tool_registry_stub(names: tuple[str, ...]) -> object:
    """最小工具注册表桩（is_registered/find/iter_defs 三方法）。"""

    class _Stub:
        def is_registered(self, name: str) -> bool:
            return name in names

        def find(self, name: str):
            return None  # 无 Schema 文本（测试系统指令不含工具）

    return _Stub()


def _default_tool_registry() -> object:
    from app.harness.execution.registry import build_default_registry

    return build_default_registry()


# ─── 1. AgentRegistry.discover：稳定性 / 能力映射 / sandbox 排除 ───


def test_discover_diagnose_and_dataset_and_fallback() -> None:
    registry = build_default_agent_registry()
    assert (
        registry.discover(capabilities=frozenset({"analyze_report"})).agent_id
        == "worker.diagnose"
    )
    assert (
        registry.discover(capabilities=frozenset({"inspect_dataset"})).agent_id
        == "worker.dataset"
    )
    assert registry.discover().agent_id == "worker.general"
    assert (
        registry.discover(
            capabilities=frozenset({"inspect_dataset", "analyze_report"})
        ).agent_id
        == "worker.general"  # 混合能力无全含 Worker → 回落通用
    )


def test_discover_sandbox_never_selected() -> None:
    """code 能力请求永不得命中 worker.sandbox（H5 前 fail-closed）。"""
    registry = build_default_agent_registry()
    result = registry.discover(capabilities=frozenset({"run_script", "verify_output"}))
    assert result.agent_id != "worker.sandbox"
    # 全量遍历保证任何能力组合都不产出 sandbox
    for def_ in registry.iter_defs():
        for capability in def_.capabilities:
            picked = registry.discover(capabilities=frozenset({capability}))
            assert picked.agent_id != "worker.sandbox"


def test_discover_stable_for_same_input() -> None:
    registry = build_default_agent_registry()
    picked = [
        registry.discover(capabilities=frozenset({"analyze_report"})).agent_id
        for _ in range(5)
    ]
    assert picked == ["worker.diagnose"] * 5


def test_discover_missing_general_fails_closed() -> None:
    registry = AgentRegistry()
    registry.register(
        AgentDef(
            agent_id="worker.diagnose",
            display_name="诊断排查",
            capabilities=frozenset({"read_workspace"}),
            allowed_tools=("read",),
        )
    )
    from app.errors import AppError

    with pytest.raises(AppError):
        registry.discover(capabilities=frozenset({"analyze_report"}))


# ─── 2. plan 节点：plan.v1 解析与 L0 降级 ───


def test_plan_node_parses_and_initializes_state() -> None:
    node = make_plan_node(_ScriptedGateway(_PLAN_OK))
    update = node(_state())
    assert update["plan_step_index"] == 0
    assert update["plan"]["intent"] == "排查并定位测试报告失败原因"
    # 预算由平台按 4 + steps*3 派生（不信任模型自报）：3 步 → 13/13
    assert update["budget"] == {"model_calls": 13, "tool_turns": 13}


def test_plan_node_l0_fallback_on_bad_protocol() -> None:
    """模型输出非 plan.v1 → build_plan L0 降级（技能合并、3–7 步）。"""
    node = make_plan_node(_ScriptedGateway("抱歉，这不是 JSON"))
    update = node(_state("对数据集 D 跑一次基准评测"))
    steps = update["plan"]["slots"]["steps"]
    assert 3 <= len(steps) <= 7
    assert "基准评测" in update["plan"]["intent"]


def test_plan_node_l0_fallback_on_model_error() -> None:
    from app.errors import AppError, ErrorCode

    gateway = _ScriptedGateway()
    gateway._errors = [AppError(ErrorCode.UPSTREAM, "上游 5xx")]
    update = make_plan_node(gateway)(_state("对 profile-A 跑一次基准评测"))
    assert 3 <= len(update["plan"]["slots"]["steps"]) <= 7
    assert update["plan"]["skill_id"] == "skill-benchmark"


def test_plan_node_rejects_step_count_out_of_range() -> None:
    """步骤数越界（2 步）视同解析失败走 L0（不静默钳制）。"""
    plan_2_steps = _PLAN_OK.replace(
        '"steps":["读取报告","定位失败用例","给出结论"]',
        '"steps":["读取报告","给出结论"]',
    )
    node = make_plan_node(_ScriptedGateway(plan_2_steps))
    update = node(_state("对数据集 D 跑一次基准评测"))
    steps = update["plan"]["slots"]["steps"]
    assert 3 <= len(steps) <= 7
    assert update["plan"]["skill_id"] == "skill-benchmark"  # L0 已正确判技能


# ─── 3. discover 节点：视野收窄与 fail-fast ───


def test_discover_node_narrows_allowed_tools() -> None:
    registry = build_default_agent_registry()
    node = make_discover_node(registry, _tool_registry_stub(("read", "TaskGet", "TaskList", "web_search")))
    update = node(_state(plan={"intent": "排查失败原因", "skill_id": None}))
    assert update["agent_id"] == "worker.diagnose"
    assert set(update["allowed_tools"]) == {"read", "TaskGet", "TaskList", "web_search"}


def test_discover_node_fail_fast_on_unregistered_tool() -> None:
    registry = build_default_agent_registry()
    node = make_discover_node(registry, _tool_registry_stub(("read",)))  # 缺 TaskGet 等
    update = node(_state(plan={"intent": "排查失败原因", "skill_id": None}))
    assert update["turn_failed"] is True
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert "未注册工具" in error["payload"]["message"]


# ─── 4. orchestrator 节点：收尾 / Act / 守卫 ───

_REACT_DONE = (
    '{"thought":"已定位原因","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n找到原因：数据集样本量不足。'
)
_REACT_READ = (
    '{"thought":"读取报告","tool":"read","arguments":{"path":"result.md"},'
    '"done":false,"protocol":"react","version":"react.v1"}'
)
# H4：orchestrator 收尾后由 reflect 判决，无失败路径需多一次受控复核短调用
_REFLECT_PASS = (
    '{"verdict":"pass","reason":"候选答复可直接给出",'
    '"clarify_question":null,"repair_hint":null,'
    '"protocol":"reflect","version":"reflect.v1"}'
)


def _orchestrator_state(**extra) -> GraphState:
    state = _state(
        plan={
            "intent": "排查失败原因",
            "skill_id": None,
            "slots": {"steps": ["读取报告", "定位", "结论"]},
            "tools_needed": ("read",),
            "delivery": "chat",
            "budget": {},
            "allows_replan": False,
            "notes": "",
        },
        agent_id="worker.diagnose",
        allowed_tools=("read", "TaskGet", "TaskList", "web_search"),
        budget=dict(DEFAULT_BUDGET),
        plan_step_index=0,
        observations=[],
    )
    state.update(extra)
    return state


def _make_orch(gateway: _ScriptedGateway, tool_names: tuple[str, ...] = ("read", "TaskGet", "TaskList", "web_search")):
    agents = build_default_agent_registry()
    return make_orchestrator_node(gateway, agents, _tool_registry_stub(tool_names))


def test_orchestrator_done_hands_off_to_reflect() -> None:
    """H4：模型 done 后不再自行收尾——只落 final_text 交 reflect 判决（防 reject 被 stop 覆盖）。"""
    gateway = _ScriptedGateway(_REACT_DONE)
    update = _make_orch(gateway)(_orchestrator_state())
    assert "样本量不足" in update["final_text"]
    assert not update.get("pending_events")  # 收尾事件由 reflect 统一产出
    assert gateway.calls == 1
    assert update["budget"]["model_calls"] == DEFAULT_BUDGET["model_calls"] - 1
    assert update["response"]["text"]  # 终态响应投影（未判决前的候选答复）


def test_orchestrator_act_emits_redacted_tool_call() -> None:
    gateway = _ScriptedGateway(_REACT_READ)
    update = _make_orch(gateway)(_orchestrator_state())
    assert update["pending_tool"]["name"] == "read"
    assert update["pending_tool"]["arguments"] == {"path": "result.md"}
    assert update["plan_step_index"] == 1
    tool_call = next(e for e in update["pending_events"] if e["kind"] == "tool_call")
    assert tool_call["payload"]["name"] == "read"
    assert "call_id" in tool_call["payload"]


def test_orchestrator_rejects_out_of_view_tool() -> None:
    """越权工具（bash 不在 diagnose 视野）→ VALIDATION fail-closed，绝不执行。"""
    react_bash = _REACT_READ.replace("read", "bash").replace("result.md", "rm -rf /")
    gateway = _ScriptedGateway(react_bash)
    update = _make_orch(gateway)(_orchestrator_state())
    assert update["turn_failed"] is True
    assert not update.get("pending_tool")
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert error["payload"]["code"] == "VALIDATION"


def test_orchestrator_budget_exhausted_guard() -> None:
    gateway = _ScriptedGateway(_REACT_DONE)
    update = _make_orch(gateway)(
        _orchestrator_state(budget={"model_calls": 0, "tool_turns": 2})
    )
    assert update["turn_failed"] is True
    assert gateway.calls == 0  # 前置守卫不调模型
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert error["payload"]["code"] == "BUDGET_EXCEEDED"


def test_orchestrator_parse_retry_cap() -> None:
    """协议解析连续失败（≥3 次）→ turn_failed，不再空转。"""
    gateway = _ScriptedGateway("不是 JSON", "还是不对", "依旧非法")
    update = _make_orch(gateway)(_orchestrator_state())
    assert update["turn_failed"] is True
    assert gateway.calls == 3  # 首次 + 2 重试后停止
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert error["payload"]["code"] == "VALIDATION"


def test_orchestrator_repeat_read_guard() -> None:
    """同参 read 已 3 次 → 第 4 次 Act 就地收尾（OR-4 守卫）。"""
    observations = [
        {
            "tool": "read",
            "text": "…",
            "ok": True,
            "arguments": {"path": "result.md"},
        }
        for _ in range(3)
    ]
    gateway = _ScriptedGateway(_REACT_READ)
    update = _make_orch(gateway)(_orchestrator_state(observations=observations))
    assert update["turn_failed"] is True
    assert not update.get("pending_tool")
    assert "重复读取已守卫" in next(
        e for e in update["pending_events"] if e["kind"] == "error"
    )["payload"]["message"]


def test_orchestrator_step_index_overflow() -> None:
    """plan_step_index 越界（slots.steps 3 步、游标 4）→ turn_failed。"""
    gateway = _ScriptedGateway(_REACT_READ)
    update = _make_orch(gateway)(_orchestrator_state(plan_step_index=4))
    assert update["turn_failed"] is True
    assert gateway.calls == 0
    assert "越界" in next(
        e for e in update["pending_events"] if e["kind"] == "error"
    )["payload"]["message"]


# ─── 5. tools 包装：预算扣减 ───


def test_tools_wrapper_consumes_tool_turns() -> None:
    async def fake_tool_node(state: GraphState) -> dict:
        return {
            "pending_events": [
                {
                    "kind": "tool_result",
                    "payload": {"name": "read", "ok": True, "truncated": False},
                }
            ],
            "observations": [{"tool": "read", "text": "…", "ok": True, "arguments": {"path": "a.md"}}],
        }

    node = make_tools_node(fake_tool_node)

    async def run() -> dict:
        return await node(_orchestrator_state(pending_tool={"name": "read", "arguments": {"path": "a.md"}}))

    result = asyncio.run(run())
    assert result["budget"]["tool_turns"] == DEFAULT_BUDGET["tool_turns"] - 1


# ─── 6. 图级：engine=agent 全链（真实工具执行 read）───


class _TalkStubGateway:
    """图级脚本：plan → read（工具轮）→ done（正文在 JSON 外）。"""

    def __init__(self):
        self.calls: list[str] = []

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        self.calls.append(str(getattr(request, "system", ""))[:20])
        return ModelResponse(text="", usage={}, latency_ms=0)


def _fake_graph_gateway(texts: list[str]):
    return _ScriptedGateway(*texts)


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


def test_taor_full_cycle_with_real_read(monkeypatch, tmp_path) -> None:
    """全链：plan → discover(diagnose) → orchestrator → tools(read 真实执行)
    → orchestrator(done)。ToolCard 事件无敏感正文；Observation 不入正文事件。"""
    _engine_on(monkeypatch)
    report = tmp_path / "result.md"
    report.write_text("失败原因：样本量不足 500 条", encoding="utf-8")
    react_done = (
        '{"thought":"已确认原因","tool":null,"arguments":{},"done":true,'
        '"protocol":"react","version":"react.v1"}\n\n结论：样本量不足。'
    )
    gateway = _fake_graph_gateway([_PLAN_OK, _REACT_READ, react_done, _REFLECT_PASS])
    agent = LangGraphAgent(gateway)
    config = {
        "configurable": {
            "credentials": {"api_key": ""},
            "sandbox": {"dir": str(tmp_path)},
        }
    }
    events = _collect(agent, _request("排查一下测试报告失败原因"), config)
    trace = _node_trace(events)
    assert trace == ["plan", "discover", "orchestrator", "tools", "orchestrator", "reflect"]
    pending = _all_pending(events)
    kinds = [event["kind"] for event in pending]
    assert "tool_call" in kinds and "tool_result" in kinds
    tool_call = next(e for e in pending if e["kind"] == "tool_call")
    assert tool_call["payload"]["name"] == "read"
    # ToolCard 摘要无正文泄露：tool_result 文本不出现在 assistant 正文之外的事件里
    for event in pending:
        if event["kind"] == "tool_call":
            text = json.dumps(event["payload"], ensure_ascii=False)
            assert "样本量不足" not in text  # 敏感正文不进 tool_call 摘要
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["engine"] == "agent"
    assert completed["payload"]["agent_id"] == "worker.diagnose"
    assistant = next(e for e in pending if e["kind"] == "assistant_message")
    assert "样本量不足" in assistant["payload"]["text"]


def test_taor_graph_blocks_out_of_view_bash(monkeypatch) -> None:
    """越权 bash（discover 永不选 sandbox）→ VALIDATION 就地收尾，无工具事件。

    H4：硬错误（turn_failed）仍进 reflect，但 L1 直接判 reject 且不调模型，
    只补一条 ``response.completed``（finish_reason=error）收尾，不再重复叙述
    （原因已由 orchestrator 的 error 事件下发）。
    """
    _engine_on(monkeypatch)
    react_bash = _REACT_READ.replace("read", "bash").replace("result.md", "rm -rf /")
    gateway = _fake_graph_gateway([_PLAN_OK, react_bash])
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), {})
    pending = _all_pending(events)
    assert not any(event["kind"] == "tool_result" for event in pending)
    error = next(e for e in pending if e["kind"] == "error")
    assert "非法工具" in error["payload"]["message"]
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "error"
    assert gateway.calls == 2  # plan + orchestrator；reflect 硬错误不调模型


def test_taor_done_without_tools(monkeypatch) -> None:
    """模型直接 done（无需工具）→ plan/discover/orchestrator → reflect 收尾，不进 tools。"""
    _engine_on(monkeypatch)
    gateway = _fake_graph_gateway([_PLAN_OK, _REACT_DONE, _REFLECT_PASS])
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), {})
    trace = _node_trace(events)
    assert trace == ["plan", "discover", "orchestrator", "reflect"]
    pending = _all_pending(events)
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "stop"


def test_taor_dataset_worker_selected_and_tools_switched(monkeypatch) -> None:
    """数据集意图 → worker.dataset（跨 Worker 视野切换端到端：allowed 含 write/edit）。"""
    _engine_on(monkeypatch)
    plan_dataset = (
        '{"intent":"整理数据集槽位清单","skill_id":null,'
        '"slots":{"steps":["检视数据集","整理槽位","输出清单"]},'
        '"tools_needed":["read","write"],"delivery":"chat",'
        '"budget":{},"allows_replan":false,"notes":"","protocol":"plan","version":"plan.v1"}'
    )
    gateway = _fake_graph_gateway([plan_dataset, _REACT_DONE, _REFLECT_PASS])
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下数据集清单"), {})
    # 从 updates 提取 discover 节点输出（端到端视野切换）
    discover_out = None
    for mode, chunk in events:
        if mode == "updates" and "discover" in chunk:
            discover_out = chunk["discover"]
    assert discover_out is not None
    assert discover_out["agent_id"] == "worker.dataset"
    assert {"write", "edit"} <= set(discover_out["allowed_tools"])
    pending = _all_pending(events)
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["agent_id"] == "worker.dataset"


def test_taor_tool_result_payload_is_controlled(monkeypatch, tmp_path) -> None:
    """tool_result 持久事件只含受控投影：无 arguments 回显、带脱敏/截断标记。"""
    _engine_on(monkeypatch)
    report = tmp_path / "result.md"
    report.write_text("失败原因：样本量不足 500 条" * 100, encoding="utf-8")  # 超长正文
    gateway = _fake_graph_gateway([_PLAN_OK, _REACT_READ, _REACT_DONE, _REFLECT_PASS])
    agent = LangGraphAgent(gateway)
    config = {
        "configurable": {
            "credentials": {"api_key": ""},
            "sandbox": {"dir": str(tmp_path)},
        }
    }
    events = _collect(agent, _request("排查一下测试报告失败原因"), config)
    pending = _all_pending(events)
    result = next(e for e in pending if e["kind"] == "tool_result")
    payload = result["payload"]
    assert "arguments" not in payload  # 不回显调用参数
    assert payload["name"] == "read"
    assert isinstance(payload.get("truncated"), bool)
    assert isinstance(payload.get("redacted"), bool)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert len(serialized) < 5000  # 持久事件体积受控（观察全文只在单回合模型输入）
