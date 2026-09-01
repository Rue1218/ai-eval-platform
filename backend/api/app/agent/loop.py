"""LangGraph 工作链路循环：Observe → Think → Act → Gate。

本模块只收紧现有 ``StateGraph`` 的条件边，不新增第二张图，也不引入
LangChain ``create_react_agent``（混合范式文档冻结：一张图、一个模型入口）。

循环语义对齐 Plan-and-Execute + ReAct + Reflexion：

```text
plan_solve ──► tools(Observe) ──► react_agent(Think/Act) ──► tools …
                    │                      │
                    └──── 确认卡已齐 ──────┴──► reflect(Gate)
```
"""

from __future__ import annotations

from collections.abc import Mapping

from app.harness.memory import GraphState
from app.harness.orchestration import from_dict, is_budget_exhausted

# 清单/提问类短工具：成功观察后从计划移除，且不视为已完成业务步骤。
PLAN_META_TOOLS = frozenset(
    {
        "task",
        "TaskCreate",
        "TaskGet",
        "TaskUpdate",
        "TaskList",
        "ask_user_question",
    }
)


def observation_tool_name(item: object) -> str:
    """从 Observation 或投影字典取出工具名。"""
    if isinstance(item, Mapping):
        return str(item.get("tool") or "")
    return str(getattr(item, "tool", "") or "")


def observation_succeeded(item: object) -> bool:
    """判断该观察是否为成功终态。"""
    if isinstance(item, Mapping):
        return item.get("ok") is True
    return getattr(item, "ok", False) is True


def remaining_plan_tools(state: GraphState) -> tuple[str, ...]:
    """从 PlanArtifact 取出尚未被成功 Observation 覆盖的短工具。

    计划内的清单/提问工具成功后只留下观察，不能再让模型重复创建同一份
    看板；失败时仍保留该工具，交给 ReAct 按失败事实决定是否修复。
    ``read`` / ``bash`` 等业务工具不在此剔除，必须等真实执行。
    """
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return ()
    raw = plan.get("tools_needed") or ()
    observed_ok = {
        observation_tool_name(item)
        for item in (state.get("observations") or ())
        if observation_succeeded(item)
    }
    return tuple(
        name
        for name in (str(item) for item in raw)
        if name.strip() and not (name in PLAN_META_TOOLS and name in observed_ok)
    )


def confirm_plan_ready_for_reflect(state: GraphState) -> bool:
    """确认卡规划的计划内短工具已观察完毕时，跳过空转 ReAct 直接进门禁。

    ``delivery=chat`` 仍须回 ReAct 生成自然语言终稿；计划里还有 read/bash 等
    未执行项时，必须把 Observation 交给 ReAct 决策，不能提前出确认卡。
    """
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return False
    if str(plan.get("delivery") or "") != "confirm":
        return False
    return not remaining_plan_tools(state)


def route_after_tools(state: GraphState) -> str:
    """ToolNode 之后的循环边：队列未空继续执行；确认卡已齐则进 reflect。

    默认预算 12/12 时 ``routing + n×(react+tools)`` 约 25 步，恰好顶到
    LangGraph 默认 ``recursion_limit=25``。预算耗尽必须 END，避免第 13 次
    模型调用撞 ``GraphRecursionError``。
    """
    if state.get("pending_tool"):
        return "tools"
    if state.get("turn_failed"):
        return "end"
    budget = from_dict(state.get("budget") or {})
    if is_budget_exhausted(budget):
        return "end"
    if confirm_plan_ready_for_reflect(state):
        return "reflect"
    return "react_agent"
