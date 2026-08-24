"""Harness 反馈层：模型辅助核对（M6 阶段 4，FB-3）。

``review`` 只允许 ``pass→clarify`` 降级，**不得**把 ``reject`` 改为 ``pass``
（FB-3 硬约束，M6-D4）。``model_call`` 为可选模型调用句柄（注入便于测试用
mock LLM 夹具）；None 时跳过模型核对，返回确定性门禁结果。
本层不定义 ``reflect_node``（M4 owner），只提供库函数。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from app.harness.contracts import Observation, PlanArtifact

ReflectVerdict = Literal["pass", "clarify", "reject"]


def review(
    plan: PlanArtifact,
    obs: Observation,
    *,
    model_call: Callable[..., object] | None = None,
) -> ReflectVerdict:
    """模型辅助核对（FB-3）。

    确定性检查先行（校验字段完整性）；可选模型核对只降级不放行：
    - 确定性失败（如 delivery=confirm 缺工具）→ reject（不变）；
    - 模型核对通过 → pass；模型核对存疑 → clarify（降级）；
    - ``reject`` 结果不可被模型改为 ``pass``（硬约束）。
    """
    # 确定性检查（不调模型）
    if not plan.tools_needed and plan.delivery == "confirm":
        return "reject"
    if not obs.ok:
        # 工具失败：需要澄清/复核，不直接放行
        return "clarify"
    if model_call is None:
        return "pass"
    # 模型辅助核对：只允许 pass→clarify 降级
    try:
        result = model_call()
        verdict = str(getattr(result, "verdict", "") or "")
    except Exception:
        verdict = ""
    if verdict == "clarify":
        return "clarify"
    return "pass"
