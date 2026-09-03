"""H1 Router 四路分流测试（开发计划 H1 阶段验收）。

覆盖：L0 确定性裁决（同输入 100% 一致）、弱信号低于阈值触发 L1、router.v1
协议解析、图集成（开关关闭时纯对话快照无 engine；开启时 completed 审计三件套
正确、engine 本轮不可变）、L1 采纳与失败回落、S1 场景零工具无 Plan。
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.agent.routing import router_node
from app.config import settings
from app.harness.memory import SerializableRequest
from app.harness.orchestration.router import decide_engine_l0
from app.harness.prompts import parse_router_v1
from app.llm import ModelResponse
from tests.hybrid.fixtures.scenarios import S1_SCENARIOS


def _serializable(text: str) -> SerializableRequest:
    """构造可序列化请求投影（图入口）。"""
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


class _ScriptGateway:
    """invoke/stream 双通道脚本桩（L1 走 invoke，chat 走 stream）。"""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[object] = []

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        text = self.script.pop(0) if self.script else "好的。"
        return ModelResponse(text=text, latency_ms=1)

    def stream(self, request: object, config: dict | None = None):
        from app.llm import ModelStreamEvent

        self.calls.append(request)
        text = self.script.pop(0) if self.script else "好的。"
        yield ModelStreamEvent(kind="content", text=text)
        yield ModelStreamEvent(kind="completed", response=ModelResponse(text=text, latency_ms=1))


class _FailGateway(_ScriptGateway):
    """invoke 一律抛异常（L1 上游失败场景）。"""

    def invoke(self, request: object, config: dict | None = None):
        self.calls.append(request)
        raise RuntimeError("upstream down")


def _collect(agent: LangGraphAgent, request: SerializableRequest) -> list[tuple[str, dict]]:
    """消费 Agent astream 全部输出。"""

    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(request):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _pending_events(events: list[tuple[str, dict]]) -> list[dict]:
    """提取全部 pending_events。"""
    return [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]


def _router_updates(events: list[tuple[str, dict]]) -> dict:
    """汇总 router 节点的状态更新（engine/confidence/reason/budget）。"""
    merged: dict = {}
    for mode, chunk in events:
        if mode != "updates":
            continue
        for node_name, update in chunk.items():
            if node_name == "router":
                merged.update(update)
    return merged


def _completed(events: list[dict]) -> dict:
    """取 response.completed 事件 payload。"""
    return next(event["payload"] for event in events if event["kind"] == "response.completed")


def _run_with_router(
    text: str,
    script: list[str] | None = None,
    *,
    gateway: _ScriptGateway | None = None,
) -> tuple[_ScriptGateway, list[tuple[str, dict]]]:
    """在引擎开关开启下驱动一次完整图执行，返回原始 astream 输出。"""
    gateway = gateway or _ScriptGateway(script or ["好的。"])
    raw = _collect(LangGraphAgent(gateway), _serializable(text))
    return gateway, raw


# ─── 1. L0 确定性裁决（ADR-1：纯函数、可复现 100%）───

_L0_CASES = [
    ("/stop", "direct"),
    ("/help", "direct"),  # H1 未恢复斜杠命令集，仍按 direct 审计、降级执行
    ("什么是 pass@1？", "chat"),
    ("对数据集 D 跑一次基准评测", "workflow"),
    ("按 profile-A 生成测试用例", "workflow"),
    ("上周 benchmark 分数掉了，排查一下原因", "agent"),
    ("帮我看看这个文件为什么报错", "agent"),
    ("读取文件 report.md", "agent"),
    ("写一个脚本统计压测结果", "agent"),
]


@pytest.mark.parametrize("text,expected", _L0_CASES)
def test_l0_decision_table(text: str, expected: str) -> None:
    """表驱动：四路引擎映射正确。"""
    assert decide_engine_l0(text).engine == expected


def test_l0_deterministic_same_input_same_output() -> None:
    """H1 硬门槛：同输入连续五次输出 100% 一致。"""
    for text, _ in _L0_CASES:
        verdicts = [decide_engine_l0(text) for _ in range(5)]
        assert len({v.engine for v in verdicts}) == 1
        assert len({v.confidence for v in verdicts}) == 1
        assert len({v.reason for v in verdicts}) == 1


def test_l0_weak_signal_below_threshold_triggers_l1_condition() -> None:
    """弱探索信号置信度低于配置阈值 0.7（L1 触发条件成立）。"""
    verdict = decide_engine_l0("帮我看看这个")
    assert verdict.engine == "agent"
    assert verdict.confidence < settings.hybrid_router_confidence_threshold
    # 强规则置信度不低于阈值
    assert decide_engine_l0("什么是 pass@1？").confidence >= 0.7


# ─── 2. router.v1 协议解析 ───


def test_parse_router_v1_accepts_valid() -> None:
    """合法 router.v1 JSON（含代码块包裹与前后文字容错）。"""
    result = parse_router_v1(
        '```json\n{"engine":"workflow","confidence":0.9,"reason":"评测意图",'
        '"skill_id":"skill-benchmark","slots":{},"protocol":"router","version":"router.v1"}\n```'
    )
    assert result["fields"]["engine"] == "workflow"
    assert result["fields"]["confidence"] == 0.9


def test_parse_router_v1_rejects_extra_and_bad_enum() -> None:
    """多余字段与非法 engine 枚举均拒绝（协议族严格不兼容）。"""
    with pytest.raises(Exception):
        parse_router_v1(
            '{"engine":"workflow","confidence":0.9,"reason":"x","hack":1,'
            '"protocol":"router","version":"router.v1"}'
        )
    with pytest.raises(Exception):
        parse_router_v1(
            '{"engine":"wizard","confidence":0.9,"reason":"x",'
            '"protocol":"router","version":"router.v1"}'
        )
    with pytest.raises(Exception):
        parse_router_v1('{"engine":"chat","confidence":1.5,"reason":"x","protocol":"router","version":"router.v1"}')


# ─── 3. 图集成：开关关闭保持纯对话快照 ───


def test_router_off_keeps_skeleton_completed_payload(monkeypatch) -> None:
    """H1 硬门槛：开关关闭时 completed payload 与骨架化一致（无 engine 字段）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", False)
    gateway = _ScriptGateway(["你好！"])
    events = _collect(LangGraphAgent(gateway), _serializable("你好"))
    payload = _completed(_pending_events(events))
    assert "engine" not in payload
    assert payload["finish_reason"] == "stop"


# ─── 4. 图集成：引擎开启后审计三件套 ───


def test_router_on_chat_request_carries_engine_audit(monkeypatch) -> None:
    """chat 意图：completed 携带 engine=chat 与置信度/理由。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    _, raw = _run_with_router("什么是 pass@1？")
    events = _pending_events(raw)
    payload = _completed(events)
    assert payload["engine"] == "chat"
    assert payload["router_confidence"] == 0.95
    assert payload["router_reason"]
    # 事件序列仍为纯对话收尾（无工具事件）
    assert [event["kind"] for event in events] == ["assistant_message", "response.completed"]


def test_router_on_workflow_and_agent_intent_recorded(monkeypatch) -> None:
    """workflow/agent 意图被记录，H1 阶段安全降级执行且不报错。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    _, wf_raw = _run_with_router("对数据集 D 跑一次基准评测")
    wf_events = _pending_events(wf_raw)
    assert _completed(wf_events)["engine"] == "workflow"
    _, ag_raw = _run_with_router("上周 benchmark 分数掉了，排查一下原因")
    ag_events = _pending_events(ag_raw)
    assert _completed(ag_events)["engine"] == "agent"
    # Router 只分流：不产工具调用、不产 Plan
    assert all(event["kind"] not in {"tool_call", "plan"} for event in wf_events + ag_events)


def test_router_engine_written_once_and_immutable(monkeypatch) -> None:
    """审查出口：engine 本轮只写一次（Router 是唯一分流点）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    gateway = _ScriptGateway(["好的。"])
    events = _collect(LangGraphAgent(gateway), _serializable("对数据集 D 跑 benchmark"))
    merged = _router_updates(events)
    assert merged["engine"] == "workflow"
    # 图内无其它节点改写 engine：router 更新仅在流程起始出现一次
    router_writes = sum(
        1
        for mode, chunk in events
        if mode == "updates"
        for node_name in chunk
        if node_name == "router"
    )
    assert router_writes == 1


# ─── 5. L1 CoT：采纳与失败回落 ───


def test_router_l1_adopts_model_engine_and_counts_budget(monkeypatch) -> None:
    """L1 采纳模型裁决、计入 budget.model_calls，reason 为平台模板文案。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", True)
    monkeypatch.setattr(settings, "hybrid_router_confidence_threshold", 0.7)
    router_json = (
        '{"engine":"chat","confidence":0.9,"reason":"用户只是弱探索闲聊",'
        '"protocol":"router","version":"router.v1"}'
    )
    gateway, raw = _run_with_router("帮我看看这个", script=[router_json, "好的。"])
    payload = _completed(_pending_events(raw))
    assert payload["engine"] == "chat"  # 采纳 L1
    merged = _router_updates(raw)
    assert merged["budget"] == {"model_calls": 1}
    # L1 走 invoke（1 次），chat 走 stream
    assert len(gateway.calls) == 2


def test_router_l1_failure_falls_back_to_l0(monkeypatch) -> None:
    """L1 上游失败：回落 L0（engine=agent），回合正常完成不报错。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", True)
    gateway = _FailGateway(["好的。"])
    _, raw = _run_with_router("帮我看看这个", gateway=gateway)
    payload = _completed(_pending_events(raw))
    assert payload["engine"] == "agent"  # L0 弱探索裁决
    assert "回落 L0" in payload["router_reason"]


def test_router_l1_disabled_no_extra_model_call(monkeypatch) -> None:
    """L1 开关关闭：低置信度文本也不调模型，纯 L0。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "hybrid_router_cot_enabled", False)
    gateway, raw = _run_with_router("帮我看看这个")
    assert _completed(_pending_events(raw))["engine"] == "agent"
    assert len(gateway.calls) == 1  # 仅 chat 一次


# ─── 6. S1 场景（tests/hybrid/fixtures） ───


def test_s1_scenarios_route_to_chat_or_direct(monkeypatch) -> None:
    """S1 简单任务：chat/direct、零工具调用、不产 PlanArtifact。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    for scenario in S1_SCENARIOS:
        _, raw = _run_with_router(scenario.user_text)
        events = _pending_events(raw)
        kinds = [event["kind"] for event in events]
        assert "tool_call" not in kinds
        assert "plan" not in kinds
        assert _completed(events)["engine"] in {"chat", "direct"}


# ─── 7. 节点级：Router 不落地副作用 ───


def test_router_node_returns_only_audit_fields() -> None:
    """Router 节点输出仅审计三件套与 budget，无事件副作用。"""
    from app.agent.routing import _latest_user_text

    request = _serializable("什么是 pass@1？")
    assert _latest_user_text(request) == "什么是 pass@1？"
    result = router_node({"request": request}, gateway=None)
    assert set(result) == {"engine", "router_confidence", "router_reason", "budget"}
    assert result["budget"] == {}
