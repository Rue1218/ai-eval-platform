"""H1 混合驱动引擎 Router 单测（开发计划 H1 阶段验收）。

覆盖：L0 纯函数五次一致性与场景标注对齐、置信度阈值两侧、L1 `router.v1`
成功采信与预算记账、L1 非法 JSON / 上游 5xx / 超时 / 预算耗尽全量回落、
L1 关闭零调用、主开关关闭的纯对话快照回归、开启后的 chat 审计字段与
四路真实分流、direct 零模型防御收尾、engine 本轮不可变
（结构断言：仅 router 节点写 engine）、`GET /api/agents` 目录投影。
全部不依赖 DB/WS/真实模型。
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events, router_audit_from_update
from app.agent.router_node import route_l0, router_node
from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.memory import SerializableRequest
from app.llm import ModelRequest, ModelResponse, ModelStreamEvent
from app.routers.agents import list_agents
from tests.hybrid.fixtures.scenarios import ALL_SCENARIOS

# L1 成功样例：合法 router.v1 JSON（workflow + 已注册技能）
_L1_OK_JSON = (
    '{"engine":"workflow","skill_id":"skill-benchmark","confidence":0.9,'
    '"reason":"要求执行基准评测","slots":{},"protocol":"router","version":"router.v1"}'
)


def _request(text: str) -> SerializableRequest:
    """构造图入口请求投影（最后一条用户消息为分流文本）。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


class _StubGateway:
    """计数型桩网关：stream 走 chat 路径，invoke 供 L1 CoT 使用。"""

    def __init__(self, invoke_text: str | None = None, invoke_error: AppError | None = None):
        self.stream_calls = 0
        self.invoke_calls: list[ModelRequest] = []
        self._invoke_text = invoke_text
        self._invoke_error = invoke_error

    def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
        self.invoke_calls.append(request)
        if self._invoke_error is not None:
            raise self._invoke_error
        return ModelResponse(text=self._invoke_text or "", latency_ms=1)

    def stream(self, request: ModelRequest, config: dict | None = None):
        self.stream_calls += 1
        return iter(
            [
                ModelStreamEvent(kind="content", text="流式答案"),
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text="流式答案", latency_ms=2),
                ),
            ]
        )


def _run(agent: LangGraphAgent, request: SerializableRequest) -> list[tuple[str, dict]]:
    """同步收集一轮 astream 输出（custom + updates）。"""

    async def collect() -> list[tuple[str, dict]]:
        return [item async for item in agent.astream(request)]

    return asyncio.run(collect())


def _completed_payload(events: list[tuple[str, dict]]) -> dict:
    """提取唯一 response.completed 的 payload。"""
    payloads = [
        event["payload"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
        if event["kind"] == "response.completed"
    ]
    assert len(payloads) == 1
    return dict(payloads[0])


def _node_output(events: list[tuple[str, dict]], node: str) -> dict | None:
    """提取指定节点的 updates 输出（engine 不可变断言用）。"""
    for mode, chunk in events:
        if mode == "updates" and node in chunk:
            return chunk[node]
    return None


@pytest.fixture
def hybrid_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """开启混合引擎主开关（L1 CoT 默认关闭，纯 L0 可复现）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", False)


# ─── 1. L0 纯函数：可复现性与场景对齐 ───


def test_l0_deterministic_five_runs_matches_scenario_labels() -> None:
    """同一输入连续五次 L0 判定完全一致，且 engine 与 S1–S4 标注吻合。"""
    for scenario in ALL_SCENARIOS:
        decisions = [route_l0(scenario.user_text) for _ in range(5)]
        assert len(set(decisions)) == 1, scenario.scenario_id
        assert decisions[0].engine == scenario.expected_engine, scenario.scenario_id
        assert 0.0 <= decisions[0].confidence <= 1.0


def test_l0_confidence_threshold_sides() -> None:
    """阈值两侧：技能词无动作 0.6 / 弱元词 0.5 触发 L1；单工具 0.75 不触发。"""
    threshold = settings.hybrid_router_confidence_threshold
    assert route_l0("什么是基准评测").confidence < threshold
    assert route_l0("你有哪些工具").confidence < threshold
    assert route_l0("读取一下文件").confidence >= threshold
    assert route_l0("/help").confidence >= threshold


def test_l0_empty_and_slash_are_deterministic() -> None:
    """空输入按 chat、斜杠按 direct（收包循环 /stop 之外的防御入口）。"""
    assert route_l0("").engine == "chat"
    assert route_l0("   ").engine == "chat"
    assert route_l0("/anything").engine == "direct"


def test_l0_router_node_workflow_no_model_no_downgrade_stamp() -> None:
    """router 节点 L0 路径零模型调用；workflow（H2 已实现）不再标注降级。"""
    gateway = _StubGateway()
    update = router_node({"request": _request("对 profile-A 跑基准评测")}, gateway)
    assert update["engine"] == "workflow"
    assert "降级" not in update["router_reason"]  # H2：workflow 由 W0–W7 DAG 执行
    assert gateway.invoke_calls == []  # L0 零模型调用


def test_l0_router_node_agent_keeps_real_engine_audit() -> None:
    """H3 已接通 Agent TAOR，Router 审计不得再谎称降级为 chat。"""
    gateway = _StubGateway()
    update = router_node({"request": _request("请排查基准评测失败原因")}, gateway)
    assert update["engine"] == "agent"
    assert "降级" not in update["router_reason"]
    assert gateway.invoke_calls == []


# ─── 2. L1 CoT：成功采信与全量回落 ───


def test_l1_success_adopts_result_and_consumes_budget(
    monkeypatch: pytest.MonkeyPatch, hybrid_on: None
) -> None:
    """低置信触发 L1：合法且有执行动作的 router.v1 采信，model_calls 12→11。"""
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", True)
    # 让该有效 Workflow 请求走 L1，以覆盖 L1 成功采信而非 L0 直判路径。
    monkeypatch.setattr(settings, "hybrid_router_confidence_threshold", 0.99)
    gateway = _StubGateway(invoke_text=_L1_OK_JSON)
    events = _run(LangGraphAgent(gateway), _request("对 profile-A 跑基准评测"))
    router_out = _node_output(events, "router")
    assert router_out is not None
    assert router_out["engine"] == "workflow"
    assert router_out["budget"] == {"model_calls": 11, "tool_turns": 12}
    assert len(gateway.invoke_calls) == 1
    l1_request = gateway.invoke_calls[0]
    assert l1_request.config.max_tokens == 256  # L1 限流输出
    # H2：engine=workflow 进入 W0–W7 DAG；无确认上下文时在 W5 发确认卡并
    # 以 completed(stop) 收尾本轮，等待确认回执重放。
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for value in chunk.values()
        if isinstance(value, dict)
        for event in value.get("pending_events", [])
    ]
    assert not [e for e in pending if e["kind"] == "error"]
    assert _completed_payload(events)["finish_reason"] == "stop"


def test_l1_workflow_without_execution_intent_falls_back_to_l0_chat(
    monkeypatch: pytest.MonkeyPatch, hybrid_on: None
) -> None:
    """L1 不得仅凭技能名词把概念问答提升为会产生确认卡的 Workflow。"""
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", True)
    gateway = _StubGateway(invoke_text=_L1_OK_JSON)
    events = _run(LangGraphAgent(gateway), _request("什么是基准评测"))
    router_out = _node_output(events, "router")
    assert router_out is not None
    assert router_out["engine"] == "chat"
    assert "缺少执行动作回落 L0" in router_out["router_reason"]
    assert not [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
        if event["kind"] == "confirm"
    ]
    assert _completed_payload(events)["engine"] == "chat"


@pytest.mark.parametrize(
    ("invoke_text", "invoke_error", "code_hint"),
    [
        ("抱歉，这不是 JSON", None, "validation"),  # 非法 JSON
        (None, AppError(ErrorCode.UPSTREAM, "上游 5xx"), "upstream"),  # 上游错误
        (None, AppError(ErrorCode.TIMEOUT, "上游超时"), "timeout"),  # 超时
    ],
)
def test_l1_failures_fall_back_to_l0(
    monkeypatch: pytest.MonkeyPatch,
    hybrid_on: None,
    invoke_text: str | None,
    invoke_error: AppError | None,
    code_hint: str,
) -> None:
    """L1 失败矩阵：格式错误/上游 5xx/超时一律回落 L0，不猜测、不异常。"""
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", True)
    gateway = _StubGateway(invoke_text=invoke_text, invoke_error=invoke_error)
    events = _run(LangGraphAgent(gateway), _request("什么是基准评测"))
    router_out = _node_output(events, "router")
    assert router_out is not None
    assert router_out["engine"] == "chat"  # L0 结论（技能词无动作 → chat）
    assert "L1 失败回落" in router_out["router_reason"]
    completed = _completed_payload(events)
    assert completed["engine"] == "chat"
    assert completed["finish_reason"] == "stop"


def test_l1_budget_exhausted_falls_back(
    monkeypatch: pytest.MonkeyPatch, hybrid_on: None
) -> None:
    """预算耗尽：L1 不执行、不抛错，回落 L0 且不消耗预算。"""
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", True)
    # 图外直调节点：get_config 在图内才有上下文，此处以空配置替身注入
    monkeypatch.setattr("app.agent.router_node.get_config", lambda: None)
    gateway = _StubGateway(invoke_text=_L1_OK_JSON)
    state = {
        "request": _request("你有哪些工具"),
        "budget": {"model_calls": 0, "tool_turns": 12},
    }
    update = router_node(state, gateway)
    assert update["engine"] == "agent"  # L0 弱元词结论
    assert "BUDGET_EXCEEDED" in update["router_reason"]
    assert "budget" not in update  # 未消费不记账
    assert gateway.invoke_calls == []


def test_l1_disabled_never_calls_model(hybrid_on: None) -> None:
    """L1 开关关闭：低置信输入也零 invoke，L0 结论即终局（100% 可复现）。"""
    gateway = _StubGateway()
    events = _run(LangGraphAgent(gateway), _request("什么是基准评测"))
    assert gateway.invoke_calls == []
    assert _completed_payload(events)["engine"] == "chat"


# ─── 3. 图拓扑：主开关与审计契约 ───


def test_main_switch_off_keeps_chat_only_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主开关关闭：事件序列与 payload 与骨架化快照完全一致（无 engine 字段）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", False)
    gateway = _StubGateway()
    events = _run(LangGraphAgent(gateway), _request("什么是 pass@1？"))
    kinds = [
        event["kind"]
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]
    assert kinds == ["assistant_message", "response.completed"]
    completed = _completed_payload(events)
    assert completed == {"finish_reason": "stop", "role": "assistant"}


def test_main_switch_on_chat_carries_router_audit(hybrid_on: None) -> None:
    """开启后 S1 简单问答：completed 携带 engine=chat 审计三元组。"""
    gateway = _StubGateway()
    events = _run(LangGraphAgent(gateway), _request("什么是 pass@1？"))
    completed = _completed_payload(events)
    assert set(completed) == {
        "finish_reason",
        "role",
        "engine",
        "router_confidence",
        "router_reason",
    }
    assert completed["engine"] == "chat"
    assert completed["router_confidence"] >= settings.hybrid_router_confidence_threshold


def test_s1_zero_tools_no_plan_single_model_call(hybrid_on: None) -> None:
    """S1 验收：简单问答零工具、无 Plan、无 Worker 字段，模型调用恰一次。"""
    gateway = _StubGateway()
    events = _run(LangGraphAgent(gateway), _request("什么是 pass@1？"))
    router_out = _node_output(events, "router")
    assert router_out is not None
    assert "plan" not in router_out
    assert "agent_id" not in router_out
    assert "allowed_tools" not in router_out
    assert gateway.stream_calls == 1  # 仅 chat 一次；Router L0 零调用
    assert gateway.invoke_calls == []


def test_engine_immutable_only_router_writes(hybrid_on: None) -> None:
    """engine 本轮不可变（结构断言）：chat/direct 节点输出均不含 engine 键。"""
    gateway = _StubGateway()
    events = _run(LangGraphAgent(gateway), _request("什么是 pass@1？"))
    chat_out = _node_output(events, "chat_stream")
    assert chat_out is not None and "engine" not in chat_out
    slash_events = _run(LangGraphAgent(_StubGateway()), _request("/help"))
    direct_out = _node_output(slash_events, "direct")
    assert direct_out is not None and "engine" not in direct_out


def test_direct_zero_model_defensive_rejection(hybrid_on: None) -> None:
    """/stop 之外的斜杠：direct 防御拒绝，零模型调用，finish_reason=error。"""
    gateway = _StubGateway()
    events = _run(LangGraphAgent(gateway), _request("/help"))
    assert gateway.stream_calls == 0
    assert gateway.invoke_calls == []
    completed = _completed_payload(events)
    assert completed["finish_reason"] == "error"
    assert completed["engine"] == "direct"
    assert completed["router_confidence"] == 1.0


def test_router_audit_from_update_helper() -> None:
    """ws.py 收尾审计提取：router 输出可提取，其他节点输出返回 None。"""
    audit = router_audit_from_update(
        {"router": {"engine": "agent", "router_confidence": 0.75, "router_reason": "r"}}
    )
    assert audit == {"engine": "agent", "router_confidence": 0.75, "router_reason": "r"}
    assert router_audit_from_update({"chat_stream": {"pending_events": []}}) is None


# ─── 4. GET /api/agents 只读目录（API.md §3.6.3） ───


def test_agents_directory_projects_sanitized_registry() -> None:
    """目录只含脱敏投影字段，不含密钥、网关或 LLM 实例引用。"""
    payload = list_agents(user=None)
    agents = payload["agents"]
    assert {agent["agent_id"] for agent in agents} >= {
        "worker.general",
        "worker.diagnose",
        "worker.dataset",
    }
    allowed_keys = {
        "agent_id",
        "display_name",
        "capabilities",
        "allowed_tools",
        "skill_ids",
        "max_permission",
        "budget",
        "model_profile_id",
        "description",
    }
    for agent in agents:
        assert set(agent) == allowed_keys
        assert agent["allowed_tools"]  # 工具视野非空
        assert "api_key" not in agent and "gateway" not in agent
