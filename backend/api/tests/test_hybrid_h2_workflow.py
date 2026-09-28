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


def test_w0_selects_only_testcase_and_rejects_retired_skills() -> None:
    """用例生成可选中；基准评测与压测意图明确拒绝。"""
    selected = select_skill_node(_state("生成一批测试用例"))
    assert selected["skill_id"] == "skill-testcase"
    assert selected["skill_candidates"] == ("skill-testcase",)
    for text in ("对数据集 D 跑一次基准评测", "发起一次压测"):
        rejected = select_skill_node(_state(text))
        assert rejected["workflow_failed"] is True
        error = next(e for e in rejected["pending_events"] if e["kind"] == "error")
        assert error["payload"]["code"] == "VALIDATION"
        assert "仅支持测试用例生成" in error["payload"]["message"]


def test_w0_rag_fail_closed() -> None:
    """rag（未接入）→ VALIDATION 就地收尾，绝不写 succeeded。"""
    update = select_skill_node(_state("跑一次 rag 评测"))
    assert update["workflow_failed"] is True
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert error["payload"]["code"] == "VALIDATION"


def test_w0_ambiguous_and_empty_reject_without_guessing() -> None:
    """并列与零命中均就地收尾（不猜测技能）。"""
    both = select_skill_node(_state("帮我跑一次基准评测和压测任务"))
    assert both["workflow_failed"] is True
    assert "当前仅支持测试用例生成" in next(
        e for e in both["pending_events"] if e["kind"] == "error"
    )["payload"]["message"]
    none = select_skill_node(_state("帮我看看这个"))
    assert none["workflow_failed"] is True


def test_w0_rejects_concept_question_before_skill_selection() -> None:
    """即使上游误进 Workflow，概念问答也不能生成确认卡或任务。"""
    update = select_skill_node(_state("什么是基准评测"))
    assert update["workflow_failed"] is True
    assert "概念问答" in next(
        event for event in update["pending_events"] if event["kind"] == "error"
    )["payload"]["message"]


def test_w0_adopts_enabled_l1_skill_before_keyword_matching() -> None:
    """L1 已验证的 skill_id 必须优先于 W0 关键词候选，避免二段路由漂移。"""
    update = select_skill_node(
        _state("跑一次未知评估任务", skill_id="skill-testcase")
    )
    assert update["skill_id"] == "skill-testcase"
    assert update["skill_candidates"] == ("skill-testcase",)


def test_w0_rejects_quality_then_stress() -> None:
    """旧先评后压意图即使归一，也不能绕过用例生成边界。"""
    update = select_skill_node(_state("跑一次基准评测，成功后压测"))
    assert update["workflow_failed"] is True
    assert "仅支持测试用例生成" in next(
        e for e in update["pending_events"] if e["kind"] == "error"
    )["payload"]["message"]


# ─── 2. W1–W4：槽位 / 加载 / 门禁 / TaskSpec ───


def test_w1_testcase_needs_no_profile_asset() -> None:
    update = prepare_slots_node(_state("生成用例", skill_id="skill-testcase"))
    assert update["slots_missing"] == ()
    assert update["slots"] == {}


def test_w2_loads_testcase_and_rejects_retired_skills() -> None:
    update = load_skill_node(_state("生成用例", skill_id="skill-testcase"))
    assert update["workflow_step"] == "W2_load_skill"
    assert not update.get("workflow_failed")
    for skill_id in ("skill-benchmark", "skill-rag", "skill-stress"):
        rejected = load_skill_node(_state("旧任务", skill_id=skill_id))
        assert rejected["workflow_failed"] is True  # 加载门禁双保险


def test_w3_only_testcase_passes_kind_gate() -> None:
    """用例生成通过 W3；旧评测与压测类型明确拒绝。"""
    ok = validate_gates_node(_state("生成用例", skill_id="skill-testcase"))
    assert ok["gate_report"]["passed"] is True
    for skill_id in ("skill-benchmark", "skill-rag", "skill-stress"):
        rejected = validate_gates_node(_state("旧任务", skill_id=skill_id))
        assert rejected["workflow_failed"] is True
        assert rejected["gate_report"]["failed_code"] == "VALIDATION"
        assert "仅支持测试用例生成" in rejected["gate_report"]["message"]


def test_w3_probe_active_task_blocks() -> None:
    update = validate_gates_node(
        _state("生成用例", skill_id="skill-testcase"),
        config={"session_probe": lambda: True},
    )
    assert update["workflow_failed"] is True
    assert update["gate_report"]["failed_code"] == "CONCURRENCY"


def test_w4_builds_task_spec_from_defaults() -> None:
    update = build_task_spec_node(_state("生成用例", skill_id="skill-testcase"))
    spec = update["task_spec"]
    assert spec["kind"] == "testcase"
    assert spec["case_source"] == {"text": ""}
    assert spec["with_stress"] is False


def test_w4_merges_explicit_case_source_without_changing_kind() -> None:
    """W4 只合并明确来源，不把用例任务改成旧评测类型。"""
    state = _state("生成用例", skill_id="skill-testcase", slots={"case_source": {"text": "登录需求"}})
    spec = build_task_spec_node(state)["task_spec"]
    assert spec["kind"] == "testcase"
    assert spec["case_source"] == {"text": "登录需求"}
    assert spec["with_stress"] is False


# ─── 3. W5–W7：确认 / 入队 / 收尾 ───


def test_w5_requires_confirm_context() -> None:
    """无确认上下文：就地收尾（批次 2 直连确认卡前不产事件）。"""
    update = await_confirm_node(_state("生成用例", skill_id="skill-testcase"))
    assert update["workflow_failed"] is True


def test_w5_confirm_missing_case_source_rejected() -> None:
    """确认卡缺少用例来源时不得进入入队节点。"""
    spec = {"kind": "testcase", "case_source": {"text": ""}}
    update = await_confirm_node(
        _state("生成用例", skill_id="skill-testcase", task_spec=spec),
        config={"workflow_confirm": {"task_spec": spec}},
    )
    assert update["workflow_failed"] is True
    error = next(e for e in update["pending_events"] if e["kind"] == "error")
    assert error["payload"]["code"] == "VALIDATION"
    assert "需求文本" in error["payload"]["message"]


def test_w5_confirm_passes_and_updates_spec() -> None:
    base = {"kind": "testcase", "case_source": {"text": ""}}
    confirm = {"task_spec": {"case_source": {"text": "登录成功后进入首页"}}}
    update = await_confirm_node(
        _state("生成用例", skill_id="skill-testcase", task_spec=base),
        config={"workflow_confirm": confirm},
    )
    assert not update.get("workflow_failed")
    assert update["task_spec"]["case_source"] == {"text": "登录成功后进入首页"}
    assert update["task_spec"]["kind"] == "testcase"


def test_w6_enqueue_requires_db_factory() -> None:
    update = enqueue_node(_state("生成用例", skill_id="skill-testcase"))
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
            "生成用例",
            skill_id="skill-testcase",
            task_spec={"kind": "testcase", "case_source": {"text": "登录需求"}},
        ),
        config={"db_factory": _FakeDb, "session_id": "s-1", "user_id": "u-1"},
    )
    assert update["enqueued_task_id"] == "task-1"
    assert len(calls) == 1
    assert calls[0][0] == "s-1" and calls[0][1] == "testcase"


def test_w7_summarize_with_engine_audit() -> None:
    update = summarize_node(
        _state("生成用例", skill_id="skill-testcase", enqueued_task_id="task-1")
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


def test_dag_full_path_five_runs_identical(engine_on, monkeypatch) -> None:
    """固定槽位请求：五次运行 W0–W7 路径 100% 一致，入队一次。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "app.harness.execution.worker_bridge.enqueue_long_task",
        lambda db, session_id, user_id, kind, spec, **kw: calls.append(kind) or "task-1",
    )
    text = "生成一批测试用例"
    confirm = {"task_spec": {"case_source": {"text": "登录需求"}}}
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
    assert calls == ["testcase"] * 5  # 每次恰好入队一次
    events = _pending(_run_workflow(text, confirm=confirm))
    assert "tool_call" not in [event["kind"] for event in events]
    completed = next(e for e in events if e["kind"] == "response.completed")
    assert completed["payload"]["engine"] == "workflow"


def test_dag_retired_task_intents_fail_closed(engine_on) -> None:
    """旧评测、RAG 与压测：error 收尾，不生成确认卡或成功消息。"""
    rag_events = _pending(_run_workflow("跑一次 rag 评测"))
    assert any(
        e["kind"] == "error" and e["payload"]["code"] == "VALIDATION"
        for e in rag_events
    )
    assert not any(e["kind"] == "assistant_message" for e in rag_events)
    rag_completed = [e for e in rag_events if e["kind"] == "response.completed"]
    assert len(rag_completed) == 1
    assert rag_completed[0]["payload"]["finish_reason"] == "error"
    for text in ("发起一次压测", "对数据集 D 跑一次基准评测"):
        events = _pending(_run_workflow(text))
        assert any(
            e["kind"] == "error" and e["payload"]["code"] == "VALIDATION"
            and "仅支持测试用例生成" in e["payload"]["message"]
            for e in events
        )
        assert not any(e["kind"] in {"confirm", "assistant_message"} for e in events)
        completed = [e for e in events if e["kind"] == "response.completed"]
        assert len(completed) == 1
        assert completed[0]["payload"]["finish_reason"] == "error"


def test_workflow_state_serializable(engine_on, monkeypatch) -> None:
    """全链终态 State JSON 可序列化（E-A1 检查点兼容）。"""
    monkeypatch.setattr(
        "app.harness.execution.worker_bridge.enqueue_long_task",
        lambda db, session_id, user_id, kind, spec, **kw: "task-1",
    )
    confirm = {"task_spec": {"case_source": {"text": "登录需求"}}}
    events = _run_workflow("生成测试用例", confirm=confirm)
    # 通过 updates 增量验证全链字段写入后可序列化
    for mode, chunk in events:
        if mode == "updates":
            for update in chunk.values():
                if isinstance(update, dict):
                    json.dumps(update)
    assert_serializable({"engine": "workflow", "skill_id": "skill-testcase"})


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
