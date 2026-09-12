"""H4 Reflection 五档判决测试（开发计划 H4 阶段验收）。

S3 人为注入失败，逐档验证 ``repair → retry → reject`` 失败阶梯与每个硬上限：

- 首档修复：``step_fail_count == 1`` 出 ``repair``，repair_hint 经 Observation
  回灌下一轮 Executor（不落库、不进事件）；
- 次档重规划：修复后仍失败出 ``retry``，``force_replan`` + ``replan_reason``
  回 plan，且 ``replan_reason`` **不参与** L0 技能关键词匹配；
- 硬上限：``MAX_REPAIRS=1`` / ``MAX_REPLANS=2`` 任一用尽即 ``reject``；
- ``reject`` 不得被误判为 ``pass``；``turn_failed=True`` 任何路径不出 ``pass``；
- ``clarify`` 不调用工具（收尾即停）；
- 预算耗尽时跳过 L3 复核，不因复核失败卡住用户。

不依赖 WS/DB；模型调用全部由脚本网关桩接替（越界即 AssertionError）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest

from app.agent import LangGraphAgent
from app.agent.taor_nodes import make_reflect_node, make_tools_node
from app.harness.contracts import Observation, PlanArtifact, from_dict
from app.harness.feedback.review import MAX_REPAIRS, MAX_REPLANS, review
from app.harness.memory import GraphState, SerializableRequest
from app.harness.orchestration.budget import DEFAULT_BUDGET
from app.harness.prompts.protocols import parse_reflect
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


def _plan_dict(**overrides) -> dict:
    plan = {
        "intent": "排查失败原因",
        "skill_id": None,
        "slots": {"steps": ["读取报告", "定位", "结论"]},
        "tools_needed": ("read",),
        "delivery": "chat",
        "budget": {},
        "allows_replan": True,
        "notes": "",
    }
    plan.update(overrides)
    return plan


def _state(text: str = "排查测试失败原因", **extra) -> GraphState:
    state: GraphState = {
        "request": _request(text),
        "engine": "agent",
        "router_confidence": 0.8,
        "router_reason": "探索排查意图（测试）",
    }
    state.update(extra)
    return state


def _reflect_state(**extra) -> GraphState:
    state = _state(
        plan=_plan_dict(),
        agent_id="worker.diagnose",
        allowed_tools=("read",),
        budget=dict(DEFAULT_BUDGET),
        plan_step_index=1,
        final_text="候选答复：样本量不足。",
    )
    state.update(extra)
    return state


def _failed_observation(text: str = "读取失败：路径不存在", hint: str = "") -> dict:
    observation = Observation(tool="read", text=text, ok=False, repair_hint=hint)
    return {
        "tool": observation.tool,
        "text": observation.text,
        "ok": observation.ok,
        "truncated": False,
        "source": None,
        "redacted": True,
        "arguments": {"path": "nope.md"},
        "display_data": {},
        "repair_hint": observation.repair_hint,
        "error_code": "NOT_FOUND",
        "recovery": {},
    }


class _ScriptedGateway:
    """按调用序号返回预置文本；超出序列抛 AssertionError（断言模型调用圈数）。"""

    def __init__(self, *texts: str):
        self._texts = list(texts)
        self.calls = 0

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        self.calls += 1
        index = self.calls - 1
        if index >= len(self._texts):
            raise AssertionError(f"模型调用超出脚本：第 {self.calls} 次")
        return ModelResponse(text=self._texts[index], usage={}, latency_ms=0)


# ─── 1. 协议：reflect.v1 五档枚举 ───


def test_reflect_protocol_accepts_five_verdicts() -> None:
    base = '"reason":"测试","protocol":"reflect","version":"reflect.v1"'
    for verdict in ("pass", "clarify", "reject", "repair", "retry"):
        fields = parse_reflect(f'{{"verdict":"{verdict}",{base}}}')["fields"]
        assert fields["verdict"] == verdict


def test_reflect_protocol_rejects_unknown_verdict() -> None:
    raw = (
        '{"verdict":"approve","reason":"x","protocol":"reflect","version":"reflect.v1"}'
    )
    with pytest.raises(Exception):  # AppError(VALIDATION)
        parse_reflect(raw)


def test_reflect_protocol_accepts_repair_hint() -> None:
    raw = (
        '{"verdict":"repair","reason":"路径写错","clarify_question":null,'
        '"repair_hint":"先列目录再读文件","protocol":"reflect","version":"reflect.v1"}'
    )
    fields = parse_reflect(raw)["fields"]
    assert fields["repair_hint"] == "先列目录再读文件"


# ─── 2. review 库：五档判决（零模型） ───


def test_review_l1_rejects_confirm_delivery_without_tools() -> None:
    plan = _plan_dict(delivery="confirm", tools_needed=())
    assert review(from_dict(PlanArtifact, plan)) == "reject"


def test_review_ladder_repair_then_retry_then_reject() -> None:
    plan = from_dict(PlanArtifact, _plan_dict())
    failed = {"step_fail_count": 1}
    # 首次失败、修复配额未用尽 → 修复
    assert review(plan, **failed) == "repair"
    # 修复配额已用尽 → 重规划
    assert review(plan, repair_count=MAX_REPAIRS, **failed) == "retry"
    # 重规划配额也用尽 → 收尾
    assert review(plan, repair_count=MAX_REPAIRS, replan_count=MAX_REPLANS, **failed) == "reject"
    # 计划不允许重规划 → 直接收尾（不重规划、也不再修复）
    plan_no_replan = from_dict(PlanArtifact, _plan_dict(allows_replan=False))
    assert review(plan_no_replan, repair_count=MAX_REPAIRS, **failed) == "reject"


def test_review_without_failure_never_enters_ladder() -> None:
    """无未解决失败时不走修复/重规划（配额再空也不空转）。"""
    plan = from_dict(PlanArtifact, _plan_dict())
    assert review(plan, step_fail_count=0) == "pass"
    assert review(plan, step_fail_count=0, replan_count=MAX_REPLANS) == "pass"


def test_review_ignores_stale_failed_observation() -> None:
    """旧失败观察不得当作「当前未解决失败」：重规划后新计划不会被误判为仍失败。

    观察是 append reducer 累积的，跨重规划仍在列表里；若以 obs.ok 为准，
    新计划刚起跑就会被判成「仍失败」，阶梯退化为连续 retry。
    """
    plan = from_dict(PlanArtifact, _plan_dict())
    stale = from_dict(Observation, _failed_observation())
    assert review(plan, stale, step_fail_count=0) == "pass"


def test_tools_wrapper_counts_rejected_without_observation() -> None:
    """拒绝路径（门禁/权限/沙箱）不产 Observation，只发 tool_result(ok=false)：
    同样计入连续失败，否则失败阶梯看不见这类失败。"""

    async def fake_rejected(state: GraphState) -> dict:
        return {
            "pending_events": [
                {
                    "kind": "tool_result",
                    "payload": {"name": "bash", "ok": False, "error": "沙箱不可用"},
                }
            ]
        }

    async def run():
        return await make_tools_node(fake_rejected)(
            _reflect_state(pending_tool={"name": "bash", "arguments": {}})
        )

    assert asyncio.run(run())["step_fail_count"] == 1


def test_review_l3_only_downgrades() -> None:
    """L3 只可把 pass 降为 clarify / reject，不得反向放行。"""
    plan = from_dict(PlanArtifact, _plan_dict())

    class _Result:
        def __init__(self, verdict: str):
            self.verdict = verdict

    assert review(plan, model_call=lambda: _Result("clarify")) == "clarify"
    assert review(plan, model_call=lambda: _Result("reject")) == "reject"
    assert review(plan, model_call=lambda: _Result("pass")) == "pass"
    # 模型异常（含非法 verdict）不得卡住用户：回落 pass
    assert review(plan, model_call=lambda: _Result("乱码")) == "pass"

    def _boom():
        raise RuntimeError("上游炸了")

    assert review(plan, model_call=_boom) == "pass"


# ─── 3. reflect 节点：L1 硬错误 / L2 阶梯 / L3 降级 ───


def test_reflect_turn_failed_never_passes() -> None:
    """turn_failed 一律 reject：不调模型、只补收尾帧（原因已由 error 事件下发）。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(_reflect_state(turn_failed=True))
    assert update["verdict"] == "reject"
    assert gateway.calls == 0  # 硬错误不调模型
    kinds = [event["kind"] for event in update["pending_events"]]
    assert kinds == ["response.completed"]
    assert update["pending_events"][0]["payload"]["finish_reason"] == "error"


def test_reflect_missing_plan_rejects_without_model() -> None:
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(_state(engine="agent"))
    assert update["verdict"] == "reject"
    assert gateway.calls == 0
    assert "计划缺失" in update["pending_events"][0]["payload"]["text"]


def test_reflect_first_failure_emits_repair_observation() -> None:
    """首档：step_fail_count=1 → repair，repair_hint 经 Observation 回灌。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(
            step_fail_count=1,
            observations=[_failed_observation(hint="先列目录确认文件名")],
        )
    )
    assert update["verdict"] == "repair"
    assert update["repair_count"] == 1  # 回合级配额消费后不归还
    assert gateway.calls == 0  # 阶梯为确定性判决，不调模型
    assert not update.get("pending_events")  # 修复档不收尾、不发事件
    observation = update["observations"][0]
    assert observation["ok"] is False  # 失败观察，供下一轮 Executor 纠正
    assert "先列目录确认文件名" in observation["text"]
    assert observation["tool"] == "reflect"


def test_reflect_repair_hint_falls_back_to_generic_advice() -> None:
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(step_fail_count=1, observations=[_failed_observation()])
    )
    assert "换用视野内允许的短工具" in update["observations"][0]["text"]


def test_reflect_second_failure_triggers_bounded_replan() -> None:
    """次档：修复后仍失败 → retry，回 plan 重规划并重置失败计数。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(
            step_fail_count=1,
            repair_count=MAX_REPAIRS,  # 修复配额已用尽
            observations=[_failed_observation(text="读取失败：权限不足")],
        )
    )
    assert update["verdict"] == "retry"
    assert update["force_replan"] is True
    assert "权限不足" in update["replan_reason"]
    assert update["replan_count"] == 1
    assert update["plan_step_index"] == 0  # 新计划从第一步起
    assert update["step_fail_count"] == 0  # 新计划的失败阶梯重新开始
    assert not update.get("pending_events")  # 重规划档不收尾


def test_reflect_rejects_when_ladder_exhausted() -> None:
    """修复与重规划均用尽 → reject，说明停在第几步（不误判为 pass）。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(
            step_fail_count=1,
            repair_count=MAX_REPAIRS,
            replan_count=MAX_REPLANS,
            observations=[_failed_observation(text="读取失败：文件缺失")],
        )
    )
    assert update["verdict"] == "reject"
    assert gateway.calls == 0
    kinds = [event["kind"] for event in update["pending_events"]]
    assert kinds == ["assistant_message", "response.completed"]
    assert update["pending_events"][1]["payload"]["finish_reason"] == "error"
    message = update["pending_events"][0]["payload"]["text"]
    assert "文件缺失" in message and "第 1 步" in message


def test_reflect_rejects_when_replan_disabled() -> None:
    """计划声明不允许重规划 → 修复一次后直接 reject，不偷偷重规划。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(
            plan=_plan_dict(allows_replan=False),
            step_fail_count=1,
            repair_count=MAX_REPAIRS,
            observations=[_failed_observation()],
        )
    )
    assert update["verdict"] == "reject"
    assert "force_replan" not in update


def test_reflect_pass_emits_final_text() -> None:
    """无失败且 L3 放行 → pass，回显 orchestrator 候选答复并正常收尾。"""
    gateway = _ScriptedGateway(
        '{"verdict":"pass","reason":"可直接给出","protocol":"reflect","version":"reflect.v1"}'
    )
    update = make_reflect_node(gateway)(_reflect_state())
    assert update["verdict"] == "pass"
    assert gateway.calls == 1  # L3 一次受控短调用
    assert update["budget"]["model_calls"] == DEFAULT_BUDGET["model_calls"] - 1
    kinds = [event["kind"] for event in update["pending_events"]]
    assert kinds == ["assistant_message", "response.completed"]
    assert update["pending_events"][0]["payload"]["text"] == "候选答复：样本量不足。"
    assert update["pending_events"][1]["payload"]["finish_reason"] == "stop"
    assert update["pending_events"][1]["payload"]["engine"] == "agent"


def test_reflect_clarify_stops_without_tools() -> None:
    """clarify 只提问收尾：不产工具调用、不回圈。"""
    gateway = _ScriptedGateway(
        '{"verdict":"clarify","reason":"目标不明确",'
        '"clarify_question":"请指定要排查的报告文件名",'
        '"protocol":"reflect","version":"reflect.v1"}'
    )
    update = make_reflect_node(gateway)(_reflect_state())
    assert update["verdict"] == "clarify"
    assert not update.get("pending_tool")
    assert not update.get("observations")
    assert update["pending_events"][0]["payload"]["text"] == "请指定要排查的报告文件名"
    assert update["pending_events"][1]["payload"]["finish_reason"] == "stop"


def test_reflect_clarify_falls_back_to_default_question() -> None:
    gateway = _ScriptedGateway(
        '{"verdict":"clarify","reason":"缺信息","clarify_question":null,'
        '"protocol":"reflect","version":"reflect.v1"}'
    )
    update = make_reflect_node(gateway)(_reflect_state())
    assert update["pending_events"][0]["payload"]["text"]  # 兜底问句非空


def test_reflect_skips_l3_when_budget_exhausted() -> None:
    """预算耗尽不空转：跳过 L3 直接放行已有候选答复（不因复核失败卡住用户）。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(budget={"model_calls": 0, "tool_turns": 3})
    )
    assert update["verdict"] == "pass"
    assert gateway.calls == 0
    assert update["pending_events"][1]["payload"]["finish_reason"] == "stop"


def test_reflect_ignores_invalid_l3_output() -> None:
    """L3 返回非法协议 → 视为无结论，回落 pass（不重试、不空转）。"""
    gateway = _ScriptedGateway("这不是 JSON")
    update = make_reflect_node(gateway)(_reflect_state())
    assert update["verdict"] == "pass"
    assert gateway.calls == 1


def test_reflect_caps_repair_by_hard_limit() -> None:
    """兜底：即便前级给出 repair，超过 MAX_REPAIRS 一律收口为 reject。"""
    gateway = _ScriptedGateway()
    update = make_reflect_node(gateway)(
        _reflect_state(
            step_fail_count=1,
            repair_count=MAX_REPAIRS + 5,  # 配额被异常抬高 → 兜底仍收口
            replan_count=MAX_REPLANS,  # 重规划也用尽 → 只能 reject
            observations=[_failed_observation()],
        )
    )
    assert update["verdict"] == "reject"


# ─── 4. tools 包装：step_fail_count 维护 ───


def test_tools_wrapper_tracks_step_fail_count() -> None:
    async def fake_tool_node(state: GraphState) -> dict:
        return {
            "pending_events": [],
            "observations": [
                {"tool": "read", "text": "…", "ok": False, "arguments": {}},
                {"tool": "read", "text": "…", "ok": True, "arguments": {}},
            ],
        }

    async def run():
        return await make_tools_node(fake_tool_node)(
            _reflect_state(pending_tool={"name": "read", "arguments": {}})
        )

    result = asyncio.run(run())
    assert result["step_fail_count"] == 1  # 本步有一次失败即累加


def test_tools_wrapper_resets_step_fail_count_on_success() -> None:
    async def fake_ok(state: GraphState) -> dict:
        return {
            "pending_events": [],
            "observations": [{"tool": "read", "text": "…", "ok": True, "arguments": {}}],
        }

    async def run():
        return await make_tools_node(fake_ok)(
            _reflect_state(
                pending_tool={"name": "read", "arguments": {}}, step_fail_count=2
            )
        )

    assert asyncio.run(run())["step_fail_count"] == 0


# ─── 5. 图级：repair → retry → reject 全阶梯 ───

_PLAN_OK = (
    '{"intent":"排查并定位测试报告失败原因","skill_id":null,'
    '"slots":{"steps":["读取报告","定位失败用例","给出结论"]},'
    '"tools_needed":["read"],"delivery":"chat",'
    '"budget":{"model_calls":12,"tool_turns":8},"allows_replan":true,'
    '"notes":"测试用计划","protocol":"plan","version":"plan.v1"}'
)
_REACT_READ = (
    '{"thought":"读取报告","tool":"read","arguments":{"path":"result.md"},'
    '"done":false,"protocol":"react","version":"react.v1"}'
)
_REACT_DONE = (
    '{"thought":"已定位原因","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n找到了：样本量不足。'
)
_REFLECT_PASS = (
    '{"verdict":"pass","reason":"可直接给出","protocol":"reflect","version":"reflect.v1"}'
)


def _collect(agent: LangGraphAgent, request: SerializableRequest, config: dict):
    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(request, config=config):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _trace(events: list[tuple[str, dict]]) -> list[str]:
    return [
        node
        for mode, chunk in events
        if mode == "updates"
        for node in chunk
        if node in {"plan", "discover", "orchestrator", "tools", "reflect"}
    ]


def _verdicts(events: list[tuple[str, dict]]) -> list[str]:
    return [
        value["verdict"]
        for mode, chunk in events
        if mode == "updates"
        for value in chunk.values()
        if isinstance(value, dict) and value.get("verdict")
    ]


def test_taor_repair_then_replan_then_pass(monkeypatch, tmp_path) -> None:
    """S3 注入失败：read 目标文件不存在（真实工具失败）→ 完整走一遍失败阶梯。

    期望 ``repair``（注入修复观察回 Executor）→ 模型仍收尾 → ``retry``（回
    plan 重规划）→ 新计划下模型直接收尾 → ``pass``。全链收敛，不空转到预算耗尽。
    """
    _engine_on(monkeypatch)
    gateway = _ScriptedGateway(
        _PLAN_OK,  # 1 首轮规划
        _REACT_READ,  # 2 首轮 Act：read（文件不存在 → 失败）
        _REACT_DONE,  # 3 首轮收尾 → reflect 判 repair
        _REACT_DONE,  # 4 修复后仍收尾 → reflect 判 retry（修复配额已用尽）
        _PLAN_OK,  # 5 重规划
        _REACT_DONE,  # 6 新计划下直接收尾
        _REFLECT_PASS,  # 7 无失败 → L3 放行
    )
    agent = LangGraphAgent(gateway)
    config = {
        "configurable": {
            "credentials": {"api_key": ""},
            "sandbox": {"dir": str(tmp_path)},
        }
    }
    events = _collect(agent, _request("排查一下测试报告失败原因"), config)
    assert _verdicts(events) == ["repair", "retry", "pass"]
    # 修复回边回 orchestrator、重规划回边回 plan，两条边都被真实走到
    assert _trace(events).count("plan") == 2
    assert _trace(events).count("reflect") == 3


def test_taor_tool_result_reaches_model_input(monkeypatch, tmp_path) -> None:
    """回归护栏（H3 遗留缺陷）：工具结果必须进入下一轮模型输入。

    两个缺陷都会表现为「模型看不到工具结果」：``native=True`` 让 observation
    被换成占位、dataclass 观察被 ``isinstance(x, Mapping)`` 静默跳过。此处以
    真实 read 成功路径断言观察是 Mapping 且正文能进入注入文本。
    """
    _engine_on(monkeypatch)
    from app.agent.taor_nodes import _observation_lines

    report = tmp_path / "result.md"
    report.write_text("失败原因：样本量不足 500 条", encoding="utf-8")
    gateway = _ScriptedGateway(_PLAN_OK, _REACT_READ, _REACT_DONE, _REFLECT_PASS)
    agent = LangGraphAgent(gateway)
    config = {
        "configurable": {
            "credentials": {"api_key": ""},
            "sandbox": {"dir": str(tmp_path)},
        }
    }
    events = _collect(agent, _request("排查一下测试报告失败原因"), config)
    observations: list[object] = []
    for mode, chunk in events:
        if mode == "updates":
            for value in chunk.values():
                if isinstance(value, dict) and value.get("observations"):
                    observations.extend(value["observations"])
    assert observations, "工具未产出任何观察"
    assert all(isinstance(item, Mapping) for item in observations)
    assert all(item.get("ok") for item in observations)
    injected = "\n".join(_observation_lines({"observations": observations}))
    assert "样本量不足" in injected  # 正文确实进入模型输入


def test_taor_repair_never_loops_forever(monkeypatch, tmp_path) -> None:
    """修复配额为回合级：修一次后模型一直直接收尾，也不得无限 repair（收敛到 reject）。"""
    _engine_on(monkeypatch)
    # 计划不允许重规划 → 修复配额用尽后只能 reject（最短的「无限修复」反例）
    plan_no_replan = _PLAN_OK.replace('"allows_replan":true', '"allows_replan":false')
    gateway = _ScriptedGateway(
        plan_no_replan,  # 1 规划（禁重规划）
        _REACT_READ,  # 2 Act：read 失败
        _REACT_DONE,  # 3 收尾 → repair
        _REACT_DONE,  # 4 修复后仍收尾 → 必须 reject，不得再 repair
    )
    agent = LangGraphAgent(gateway)
    config = {
        "configurable": {
            "credentials": {"api_key": ""},
            "sandbox": {"dir": str(tmp_path)},
        }
    }
    events = _collect(agent, _request("排查一下测试报告失败原因"), config)
    assert _verdicts(events) == ["repair", "reject"]
    assert gateway.calls == 4  # 不再产生第 5 次调用（已收敛）


def test_taor_ladder_terminates_with_reject(monkeypatch) -> None:
    """重规划用尽后必须可读收尾：不空转到预算耗尽，也不静默出 pass。"""
    _engine_on(monkeypatch)
    # 计划不允许重规划 → 修复一次后即 reject（阶梯最短闭环）
    plan_no_replan = _PLAN_OK.replace('"allows_replan":true', '"allows_replan":false')
    react_bad = (
        '{"thought":"删除文件","tool":"bash","arguments":{"command":"rm -rf /"},'
        '"done":false,"protocol":"react","version":"react.v1"}'
    )
    gateway = _ScriptedGateway(plan_no_replan, react_bad)
    agent = LangGraphAgent(gateway)
    events = _collect(agent, _request("排查一下测试报告失败原因"), {})
    pending = [
        event
        for mode, chunk in events
        if mode == "updates"
        for value in chunk.values()
        if isinstance(value, dict)
        for event in value.get("pending_events", [])
    ]
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "error"
    assert not any(e["kind"] == "tool_result" for e in pending)


def test_taor_replan_reason_never_matches_skill_keywords(monkeypatch) -> None:
    """replan_reason 只进 notes：不得让失败文本里的词命中技能（防误判为压测/评测）。"""
    _engine_on(monkeypatch)
    from app.agent.taor_nodes import make_plan_node

    gateway = _ScriptedGateway(_PLAN_OK)
    update = make_plan_node(gateway)(
        _state(
            force_replan=True,
            replan_reason="跑基准评测失败：数据集不存在",
            budget=dict(DEFAULT_BUDGET),
        )
    )
    plan = update["plan"]
    # 失败原因写进 notes（供模型与复核消费）
    assert "数据集不存在" in plan["notes"]
    # 但不得因此把计划识别成压测/评测技能
    assert plan["skill_id"] is None
    assert plan["delivery"] == "chat"
    # 重规划沿用剩余预算，不因换计划放大回合预算
    assert update["budget"] == dict(DEFAULT_BUDGET)
    assert update["force_replan"] is False
    assert update["step_fail_count"] == 0
