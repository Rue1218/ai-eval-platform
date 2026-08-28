"""回归测试：多步任务预算充足 + task_state 收尾归一（总结步骤不阻塞交付）。

背景（生产实测）：4 步任务（write→read→edit→总结）在完成 3 步后
BUDGET_EXCEEDED；且最终 task_state can_deliver=False、总结步骤永远
current_step——预算公式 2+steps 与 native 每工具 2 次模型调用不匹配，
总结类纯文本步骤被误纳入 missing_info 无法闭环。
"""

from app.agent.react import _finalize_task_state
from app.harness.contracts import Observation
from app.harness.contracts.task_state import evolve_task_state
from app.harness.orchestration.plan import _l0_fallback, task_state_from_plan


def _plan_for(text: str):
    plan = _l0_fallback(text)
    assert plan is not None
    return plan


def test_plan_budget_scales_with_tool_steps() -> None:
    """预算派生：随步骤数按 4 + steps*3 缩放、上限 20（native 每工具 2 次 + 固定开销）。"""
    plan = _plan_for("依次用 read 读取 a.txt，write 写入 b.txt，edit 修改 c.txt，再总结结果")
    steps = len(plan.slots["steps"])
    assert steps >= 4
    expected = min(20, max(6, 4 + steps * 3))
    assert plan.budget["model_calls"] == expected
    assert plan.budget["tool_turns"] == expected
    # 4 步任务实测 ≥12 次调用：新公式（≥16）必须大于默认 12
    if steps >= 4:
        assert plan.budget["model_calls"] >= 16


def test_missing_info_excludes_summary_steps() -> None:
    """总结类纯文本步骤不进入 missing_info（无工具闭环，否则 can_deliver 恒 False）。"""
    plan = _plan_for("依次用 read 读取 a.txt，write 写入 b.txt，edit 修改 c.txt，最后总结结果")
    state = task_state_from_plan(plan)
    assert not any("总结" in item for item in state.missing_info)
    assert state.missing_info  # 工具步骤仍是缺口


def test_evolve_completes_tool_steps_and_deliverable() -> None:
    """工具步骤完成后 missing_info 清空、can_deliver=True。"""
    plan = _plan_for("用 read 读取 a.txt，write 写入 b.txt，最后总结")
    state = task_state_from_plan(plan)
    state = evolve_task_state(state, [Observation(tool="read", text="内容X", ok=True)])
    state = evolve_task_state(state, [Observation(tool="write", text="写入成功", ok=True)])
    assert len(state.completed_steps) == 2
    assert not state.missing_info
    assert state.can_deliver is True


def test_finalize_task_state_marks_summary_complete() -> None:
    """模型无工具收尾时，current_step（说明类步骤）并入完成并置可交付。"""
    plan = _plan_for("用 read 读取 a.txt，用 write 写入 b.txt，用 edit 修改 c.txt")
    state = task_state_from_plan(plan)
    state = evolve_task_state(state, [Observation(tool="read", text="内容", ok=True)])
    assert state.current_step  # 总结步骤仍是 current
    finalized = _finalize_task_state(state)
    assert finalized is not None
    assert finalized["can_deliver"] is True
    assert finalized["phase"] == "completed"
    assert state.current_step in finalized["completed_steps"]
    assert finalized["current_step"] == ""


def test_budget_cap_20() -> None:
    """预算上限 20 兜底（plan 多步任务本就多轮）。"""
    plan = _l0_fallback(
        "请执行任务：用 read 读取 a，write 写 b，edit 改 c，bash 运行 d，read 读 e，write 写 f，edit 改 g，再总结"
    )
    assert plan is not None
    assert plan.budget["model_calls"] <= 20
    assert plan.budget["model_calls"] > 12
