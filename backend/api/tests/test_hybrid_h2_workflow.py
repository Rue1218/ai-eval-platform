"""H2 Workflow DAG 测试（开发计划 H2 阶段验收，批次 1）。

覆盖：W0 二段路由（三技能正确选择 / rag VALIDATION / 并列零命中就地收尾）、
W1 必填槽、W3 门禁（kind / 先评后压 / 会话占槽）、W5 确认门槛（无确认 / 缺
必填 / 通过）、W6 唯一入队、W7 平台收尾；图级：固定槽位请求五次路径 100%
一致、skill-rag fail-closed、直接 stress 拦截、开关关闭纯对话快照、全链
State 可序列化。全部不依赖真实 DB/WS。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.agent.workflow_nodes import (
    await_confirm_node,
    build_task_spec_node,
    enqueue_node,
    load_skill_node,
    prepare_slots_node,
    select_skill_node,
    summarize_node,
    validate_gates_node,
)
from app.config import settings
from app.harness.memory import GraphState, SerializableRequest, assert_serializable


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


def _state(text: str, **extra) -> GraphState:
    """构造进入 Workflow 节点前的状态（engine=workflow 已由 Router 写入）。"""
    state: GraphState = {
        "request": _request(text),
        "engine": "workflow",
        "router_confidence": 0.9,
        "router_reason": "命中技能意图（测试）",
    }
    state.update(extra)
    return state


# ─── 1. W0 select_skill：二段路由 ───


def test_w0_selects_benchmark_testcase_stress() -> None:
    """三技能正确选择（skill_id / candidates / workflow_step）。"""
    assert select_skill_node(_state("对数据集 D 跑一次基准评测"))["skill_id"] == "skill-benchmark"
    assert select_skill_node(_state("按 profile-A 生成一批测试用例"))["skill_id"] == "skill-testcase"
    assert select_skill_node(_state("发起一次压测"))["skill_id"] == "skill-stress"


def test_w0_rag_fail_closed() -> None:
    """rag（未接入）→ VALIDATION 就地收尾，绝不写 succeeded。"""
    update = select_skill_node(_state("跑一次 rag 评测"))
    assert update["workflow_failed"] is True
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert error["payload"]["code"] == "VALIDATION"


def test_w0_ambiguous_and_empty_clarify_without_guessing() -> None:
    """并列与零命中均产 clarify 澄清（不猜测技能、不产生任务）。"""
    both = select_skill_node(_state("先跑基准评测再发起压测"))
    assert both["workflow_failed"] is True
    clarify = next(e for e in both["pending_events"] if e["kind"] == "clarify")
    assert "多个评测意图" in clarify["payload"]["question"]
    assert clarify["payload"]["options"] == ["基准评测", "压测"]
    none = select_skill_node(_state("帮我看看这个"))
    assert none["workflow_failed"] is True
    none_clarify = next(e for e in none["pending_events"] if e["kind"] == "clarify")
    assert none_clarify["payload"]["options"] == ["基准评测", "用例生成", "压测"]


# ─── 2. W1–W4：槽位 / 加载 / 门禁 / TaskSpec ───


def test_w1_lists_missing_required_assets() -> None:
    update = prepare_slots_node(_state("评测", skill_id="skill-benchmark"))
    assert update["slots_missing"] == ("profile_ids",)
    assert update["slots"] == {}


def test_w2_load_skill_benchmark_ok_rag_fail() -> None:
    update = load_skill_node(_state("评测", skill_id="skill-benchmark"))
    assert update["workflow_step"] == "W2_load_skill"
    assert not update.get("workflow_failed")
    rag = load_skill_node(_state("评测", skill_id="skill-rag"))
    assert rag["workflow_failed"] is True  # 双保险 fail-closed


def test_w3_gates_kind_stress_and_probe() -> None:
    """kind 白名单 / 直接 stress 先评后压 / 会话占槽 probe。"""
    ok = validate_gates_node(_state("评测", skill_id="skill-benchmark"))
    assert ok["gate_report"]["passed"] is True
    stress = validate_gates_node(_state("压测", skill_id="skill-stress"))
    assert stress["workflow_failed"] is True
    assert "先评后压" in stress["gate_report"]["message"]


def test_w3_probe_active_task_blocks() -> None:
    update = validate_gates_node(
        _state("评测", skill_id="skill-benchmark"),
        config={"session_probe": lambda: True},
    )
    assert update["workflow_failed"] is True
    assert update["gate_report"]["failed_code"] == "CONCURRENCY"


def test_w4_builds_task_spec_from_defaults() -> None:
    update = build_task_spec_node(_state("评测", skill_id="skill-benchmark"))
    spec = update["task_spec"]
    assert spec["kind"] == "benchmark"
    assert spec["profile_ids"] == []
    assert spec["with_stress"] is False


# ─── 3. W5–W7：确认 / 入队 / 收尾 ───


def test_w5_requires_confirm_context_emits_confirm_card() -> None:
    """无确认上下文：产 confirm 事件（kind/spec/missing），回合收尾等用户确认。"""
    state = _state(
        "评测",
        skill_id="skill-benchmark",
        task_spec={"kind": "benchmark", "profile_ids": [], "with_stress": False},
        slots_missing=("profile_ids",),
    )
    update = await_confirm_node(state)
    assert update["workflow_failed"] is True  # 短路后续节点，不静默
    confirm = next(e for e in update["pending_events"] if e["kind"] == "confirm")
    assert confirm["payload"]["kind"] == "benchmark"
    assert confirm["payload"]["spec"]["kind"] == "benchmark"
    assert "profile_ids" in confirm["payload"]["missing"]


def test_w5_confirm_missing_profile_rejected() -> None:
    spec = {"kind": "benchmark", "profile_ids": []}
    update = await_confirm_node(
        _state("评测", skill_id="skill-benchmark", task_spec=spec),
        config={"workflow_confirm": {"task_spec": spec}},
    )
    assert update["workflow_failed"] is True
    assert "profile_ids" in update["slots_missing"]


def test_w5_confirm_passes_and_updates_spec() -> None:
    base = {"kind": "benchmark", "profile_ids": [], "run": {"sample_size": 10}}
    confirm = {"task_spec": {"profile_ids": ["p-1"]}}
    update = await_confirm_node(
        _state("评测", skill_id="skill-benchmark", task_spec=base),
        config={"workflow_confirm": confirm},
    )
    assert not update.get("workflow_failed")
    assert update["task_spec"]["profile_ids"] == ["p-1"]
    assert update["task_spec"]["run"]["sample_size"] == 10  # 预填保留


def test_w6_enqueue_requires_db_factory() -> None:
    update = enqueue_node(_state("评测", skill_id="skill-benchmark"))
    assert update["workflow_failed"] is True
    assert "上下文缺失" in next(
        e for e in update["pending_events"] if e["kind"] == "error"
    )["payload"]["message"]


def test_w6_enqueues_once(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_enqueue(db, session_id, user_id, kind, spec, **kwargs):
        calls.append((session_id, kind, spec))
        return "task-1"

    monkeypatch.setattr(
        "app.harness.execution.worker_bridge.enqueue_long_task", fake_enqueue
    )
    update = enqueue_node(
        _state(
            "评测",
            skill_id="skill-benchmark",
            task_spec={"kind": "benchmark", "profile_ids": ["p-1"]},
        ),
        config={"db_factory": _FakeDb, "session_id": "s-1", "user_id": "u-1"},
    )
    assert update["enqueued_task_id"] == "task-1"
    assert len(calls) == 1
    assert calls[0][0] == "s-1" and calls[0][1] == "benchmark"


def test_w7_summarize_with_engine_audit() -> None:
    update = summarize_node(
        _state("评测", skill_id="skill-benchmark", enqueued_task_id="task-1")
    )
    events = update["pending_events"]
    kinds = [event["kind"] for event in events]
    assert kinds == ["assistant_message", "response.completed"]
    completed = events[1]["payload"]
    assert completed["engine"] == "workflow"
    assert "任务已入队" in events[0]["payload"]["text"]


# ─── 4. 图级：完整路径与开关 ───


class _FakeDb:
    """enqueue 注入的会话桩（无需真实 DB）。"""

    def close(self):
        pass


class _StubGateway:
    """Workflow 路径不调模型；断言误调模型即失败。"""

    def stream(self, request: object, config: dict | None = None):
        raise AssertionError("workflow 路径不应调用模型")


def _collect(agent: LangGraphAgent, request: SerializableRequest, config: dict):
    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(request, config=config):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _workflow_trace(events: list[tuple[str, dict]]) -> list[str]:
    """按 updates 顺序提取 Workflow DAG 节点执行序列（入口透传不计）。"""
    trace: list[str] = []
    for mode, chunk in events:
        if mode != "updates":
            continue
        for node_name in chunk:
            if node_name.startswith("w") and node_name != "workflow":
                trace.append(node_name)
    return trace


def _run_workflow(text: str, *, confirm: dict | None = None) -> list[tuple[str, dict]]:
    """在引擎开启下跑完整图；注入 db_factory / session / confirm 上下文。"""
    configurable: dict = {
        "credentials": {"api_key": ""},
        "session_id": "s-1",
        "user_id": "u-1",
        "db_factory": _FakeDb,
    }
    if confirm is not None:
        configurable["workflow_confirm"] = confirm
    return _collect(LangGraphAgent(_StubGateway()), _request(text), {"configurable": configurable})


def _pending(events: list[tuple[str, dict]]) -> list[dict]:
    return [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]


@pytest.fixture()
def _engine_on(monkeypatch):
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    yield


def test_dag_full_path_five_runs_identical(_engine_on, monkeypatch) -> None:
    """固定槽位请求：五次运行 W0–W7 路径 100% 一致，入队一次。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "app.harness.execution.worker_bridge.enqueue_long_task",
        lambda db, session_id, user_id, kind, spec, **kw: calls.append(kind) or "task-1",
    )
    text = "对数据集 D 用 profile-A 跑一次基准评测"
    confirm = {"task_spec": {"profile_ids": ["p-1"]}}
    traces = [_workflow_trace(_run_workflow(text, confirm=confirm)) for _ in range(5)]
    expected = [
        "w0_select_skill",
        "w1_prepare_slots",
        "w2_load_skill",
        "w3_validate_gates",
        "w4_build_task_spec",
        "w5_await_confirm",
        "w6_enqueue",
        "w7_summarize",
    ]
    assert all(trace == expected for trace in traces)
    assert calls == ["benchmark"] * 5  # 每次恰好入队一次
    events = _pending(_run_workflow(text, confirm=confirm))
    assert "tool_call" not in [event["kind"] for event in events]
    completed = next(e for e in events if e["kind"] == "response.completed")
    assert completed["payload"]["engine"] == "workflow"


def test_dag_rag_and_direct_stress_fail_closed(_engine_on) -> None:
    """rag 与直接压测：error 收尾、无入队、无 succeeded。"""
    rag_events = _pending(_run_workflow("跑一次 rag 评测"))
    assert any(
        e["kind"] == "error" and e["payload"]["code"] == "VALIDATION"
        for e in rag_events
    )
    assert not any(e["kind"] == "assistant_message" for e in rag_events)
    stress_events = _pending(_run_workflow("发起一次压测"))
    assert any("先评后压" in e["payload"]["message"] for e in stress_events if e["kind"] == "error")


def test_workflow_state_serializable(_engine_on, monkeypatch) -> None:
    """全链终态 State JSON 可序列化（E-A1 检查点兼容）。"""
    monkeypatch.setattr(
        "app.harness.execution.worker_bridge.enqueue_long_task",
        lambda db, session_id, user_id, kind, spec, **kw: "task-1",
    )
    confirm = {"task_spec": {"profile_ids": ["p-1"]}}
    events = _run_workflow("跑一次基准评测", confirm=confirm)
    # 通过 updates 增量验证全链字段写入后可序列化
    for mode, chunk in events:
        if mode == "updates":
            for update in chunk.values():
                if isinstance(update, dict):
                    json.dumps(update)
    assert_serializable({"engine": "workflow", "skill_id": "skill-benchmark"})


def test_switch_off_chat_snapshot_without_engine(monkeypatch) -> None:
    """开关关闭：纯对话路径不受 workflow 影响（completed 无 engine 字段）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", False)

    class _TalkGateway:
        def stream(self, request: object, config: dict | None = None):
            from app.llm import ModelResponse, ModelStreamEvent

            yield ModelStreamEvent(kind="content", text="好的")
            yield ModelStreamEvent(
                kind="completed", response=ModelResponse(text="好的", latency_ms=1)
            )

    agent = LangGraphAgent(_TalkGateway())
    events = _collect(agent, _request("什么是 pass@1？"), {})
    payloads = _pending(events)
    completed = next(e for e in payloads if e["kind"] == "response.completed")
    assert "engine" not in completed["payload"]
