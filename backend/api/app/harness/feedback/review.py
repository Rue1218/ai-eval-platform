"""Harness 反馈层：Reflection 五档判决（M6 阶段 4 + 开发计划 H4）。

判决分三级（开发计划 H4 / 架构 §3.5），越靠前越确定，**前级有结论即不再问后级**：

- **L1 规则**（确定性、零模型）：计划自身的硬矛盾（如 ``delivery=confirm``
  却不声明任何工具）直接 ``reject``；本轮硬错误（``turn_failed``）由 reflect
  节点在调用本函数前短路为 ``reject``——``reject`` 永不被后级放行（FB-3）。
- **L2 计算**（零模型）：工具失败阶梯。首次失败 ``repair``（回 Executor 再试
  一次，``MAX_REPAIRS=1``）；修复后仍失败且允许重规划则 ``retry``（回 Planner，
  ``MAX_REPLANS=2``）；两档用尽则 ``reject``。
- **L3 推理**（一次短模型调用）：仅在 L1/L2 均无结论（无失败）时核对，且
  **只降级不放行**——模型只能把 ``pass`` 降为 ``clarify`` / ``reject``，
  不得反向放行（FB-3 硬约束）。

``model_call`` 为可选模型调用句柄（注入便于测试用 mock LLM 夹具）；None 时
跳过 L3，返回 L1/L2 的确定性结论。本层不定义 ``reflect_node``（由 app.agent
层的 reflect 节点调用），只提供库函数。

阈值常量 ``MAX_REPAIRS`` / ``MAX_REPLANS`` 定义在本模块（唯一来源），禁止在
调用点散落魔法数（架构 §4.2 裁决）。总纠正机会口径为
``step_fail_count + replan_count ≤ 3``（架构 §6.2 Reflection 修复成功率指标）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from app.harness.contracts import Observation, PlanArtifact

# 五档判决（H4）：与 app.harness.memory.state.ReflectVerdict 同源；
# 此处显式重声明，避免反馈层反向依赖记忆层类型（分层：feedback ← contracts）。
ReflectVerdict = Literal["pass", "clarify", "reject", "retry", "repair"]

# 失败阶梯硬上限（开发计划 H4：修复最多一次、重规划最多两次并收敛）
MAX_REPAIRS = 1
MAX_REPLANS = 2


def review(
    plan: PlanArtifact,
    obs: Observation | None = None,
    *,
    model_call: Callable[..., object] | None = None,
    step_fail_count: int = 0,
    repair_count: int = 0,
    replan_count: int = 0,
) -> ReflectVerdict:
    """Reflection 五档判决（FB-3 硬约束：L3 只降级不放行）。

    - L1：``delivery=confirm`` 且未声明工具 → ``reject``（不调模型、不可被改写）；
    - L2：存在未解决的工具失败 → 按**回合级**配额走 ``repair → retry → reject``
      阶梯：修复配额未用尽先 ``repair``，否则允许重规划就 ``retry``，两档用尽
      即 ``reject``；
    - L3：无失败时才调用模型核对，只允许 ``pass → clarify`` / ``pass → reject``
      降级；模型不可用或返回非法值一律回 ``pass``（不因核对失败而卡住用户）。

    两条容易踩空的实现约束（均由 H4 联调实测得出）：

    1. 配额判定一律用 ``repair_count`` / ``replan_count``（回合级，消费即不还）。
       若改用失败计数当配额，模型在修复后直接收尾（不再调工具）时计数不再增长，
       会退化成**无限修复**——这正是开发计划 H4 要消灭的「无限修复/重规划」。
    2. 「当前是否存在未解决失败」只以 ``step_fail_count`` 为准，**不取**
       ``obs.ok``。观察是 append reducer 累积的，重规划后旧失败观察仍在列表里；
       以它为准会让新计划刚起跑就被判为「仍失败」，阶梯退化成连续 retry。
       ``step_fail_count`` 由 tools 节点维护：本步全成功或重规划时归零。

    ``obs`` 保留为可选入参（历史签名与 FB-3 调用方），不参与失败判定。
    """
    # ── L1 规则（确定性，零模型）──
    if not plan.tools_needed and plan.delivery == "confirm":
        return "reject"

    # ── L2 计算（零模型）：失败阶梯，配额为回合级硬上限 ──
    if step_fail_count > 0:
        if repair_count < MAX_REPAIRS:
            # 还有修复配额：注入修复观察回 Executor 再试一次
            return "repair"
        if plan.allows_replan and replan_count < MAX_REPLANS:
            # 修复配额已用尽：换计划（有界重规划，硬上限 2 次）
            return "retry"
        # 修复与重规划配额均已用尽（或计划不允许重规划）：以可读原因收尾
        return "reject"

    # ── L3 推理（可选模型核对）：只降级不放行 ──
    if model_call is None:
        return "pass"
    try:
        result = model_call()
        verdict = str(getattr(result, "verdict", "") or "")
    except Exception:
        verdict = ""
    if verdict in ("clarify", "reject"):
        return verdict  # type: ignore[return-value]
    return "pass"
