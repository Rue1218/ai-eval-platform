"""F0/P3 编造对账护栏测试（《Agent 原生工具装配方案》V0.4 §5 P3，R3-M6）。

覆盖：声明-证据检测纯函数（确认卡/任务声明命中、证据放行、非目标声明不误报）、
reflect L1.5 图级（编造 → 修复提示一次 → 复现 → reject + fabrication 审计
事件；修正后正常收尾）。对账与原生/文本路径无关，全档位生效，不依赖 WS/DB。
"""

from __future__ import annotations

import asyncio

from app.agent import LangGraphAgent
from app.agent.taor_nodes import _fabrication_claim
from app.harness.memory import SerializableRequest
from tests._helpers import enable_hybrid_engine as _engine_on

_PLAN_OK = (
    '{"intent":"排查并定位测试报告失败原因","skill_id":null,'
    '"slots":{"steps":["读取报告","定位失败用例","给出结论"]},'
    '"tools_needed":["read"],"delivery":"chat",'
    '"budget":{"model_calls":6,"tool_turns":4},"allows_replan":false,'
    '"notes":"测试用计划","protocol":"plan","version":"plan.v1"}'
)
_DONE_CLAIM_CARD = (
    '{"thought":"完成","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n我已向您发送了确认卡，请查收。'
)
_DONE_CLAIM_TASK = (
    '{"thought":"完成","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n已创建评测任务并在队列中。'
)
_DONE_OK = (
    '{"thought":"完成","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n未发现需要工具操作的事项，已完成说明。'
)
_REFLECT_PASS = (
    '{"verdict":"pass","reason":"候选答复可直接给出",'
    '"clarify_question":null,"repair_hint":null,'
    '"protocol":"reflect","version":"reflect.v1"}'
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


class _ScriptedGateway:
    def __init__(self, *texts: str):
        self._texts = list(texts)
        self.calls = 0

    def invoke(self, request: object, config: dict | None = None):
        if self.calls >= len(self._texts):
            raise AssertionError(f"模型调用超出脚本：第 {self.calls} 次")
        from app.llm import ModelResponse

        text = self._texts[self.calls]
        self.calls += 1
        return ModelResponse(text=text, usage={}, latency_ms=0)


def _state(final_text: str, observations: list[dict]) -> dict:
    return {
        "final_text": final_text,
        "observations": observations,
    }


# ─── 1. 声明-证据检测纯函数 ───


def test_claim_detects_card_without_evidence() -> None:
    assert _fabrication_claim(_state("我已向您发送了确认卡。", [])) == "向用户发送确认卡"


def test_claim_detects_task_without_evidence() -> None:
    assert _fabrication_claim(_state("已创建评测任务。", [])) == "创建或入队评测任务"


def test_claim_evidence_from_round_tools_clears() -> None:
    """本回合存在对应工具成功观察 → 放行（真实执行后有据可依）。"""
    card_evidence = [
        {"tool": "ask_user_question", "ok": True, "text": "用户已回复提问：…"},
        {"tool": "read", "ok": True, "text": "…", "arguments": {"path": "a.md"}},
    ]
    assert _fabrication_claim(_state("我已向您发送了确认卡。", card_evidence)) is None
    task_evidence = [
        {"tool": "task", "ok": True, "text": "评测任务已创建…"},
    ]
    assert _fabrication_claim(_state("已创建评测任务。", task_evidence)) is None
    # 仅 ask_user/read 证据不构成任务创建证据（任务声明仍需 task 系工具）
    assert _fabrication_claim(_state("已创建评测任务。", card_evidence)) is not None


def test_claim_unrelated_statements_not_flagged() -> None:
    """窄词表：文件/搜索/一般完成类声明不触发（防历史转述误报）。"""
    text = "已读取报告文件并核对数据，分析完成，建议补充样本量。"
    assert _fabrication_claim(_state(text, [])) is None


def test_claim_empty_text_skipped() -> None:
    assert _fabrication_claim(_state("", [])) is None


# ─── 2. reflect L1.5 图级：修复一次 → 复现 reject + fabrication 事件 ───


def test_fabrication_repair_then_reject_with_audit(monkeypatch) -> None:
    """编造声明 → 修复提示一次 → 复现 → reject + fabrication 审计事件。"""
    _engine_on(monkeypatch)
    gateway = _ScriptedGateway(_PLAN_OK, _DONE_CLAIM_CARD, _DONE_CLAIM_CARD)
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), {})
    pending = _all_pending(events)
    assert gateway.calls == 3  # plan + orchestrator×2；reject 不调 L3
    fabrication = [e for e in pending if e["kind"] == "fabrication"]
    assert len(fabrication) == 1
    assert fabrication[0]["payload"]["claim"] == "向用户发送确认卡"
    assert fabrication[0]["payload"]["repairs"] == 1
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "error"
    # 修复提示确实回灌过：第一次 reflect 判 repair → orchestrator 二次进入 →
    # 复现 → 第二次 reflect reject（不调 L3）
    trace = _node_trace(events)
    assert trace == ["plan", "discover", "orchestrator", "reflect", "orchestrator", "reflect"]


def test_fabrication_corrected_after_repair_passes(monkeypatch) -> None:
    """编造声明 → 修复提示 → 模型改述（无声明）→ 正常 pass 收尾（无事件）。"""
    _engine_on(monkeypatch)
    gateway = _ScriptedGateway(_PLAN_OK, _DONE_CLAIM_TASK, _DONE_OK, _REFLECT_PASS)
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), {})
    pending = _all_pending(events)
    assert not any(e["kind"] == "fabrication" for e in pending)
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "stop"
    assistant = next(e for e in pending if e["kind"] == "assistant_message")
    assert "工具操作" in assistant["payload"]["text"]
