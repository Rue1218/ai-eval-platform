"""混合驱动引擎四类基准场景语料（开发计划 §4.2，H0 建立、H1 起复用）。

S1–S4 固定语料与期望标注：模型自由文本不作为断言对象——Router、State、
事件、门禁与预算才是可复现断言对象（§4.1）。期望 ``engine`` 字段随 H1
Router 落地后生效；H0 仅提供语料与标注结构。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HybridScenario:
    """一条基准场景：用户文本 + 期望分流与范式路径标注。

    ``expected_engine`` 为四路之一（direct/chat/workflow/agent）；
    ``expects_plan`` 表示是否期望产出 ``PlanArtifact``；
    ``tool_calls`` 为 0 表示该场景禁止任何工具调用（S1）。
    """

    scenario_id: str
    user_text: str
    expected_engine: str = "chat"
    expects_plan: bool = False
    tool_calls: int = 0
    notes: str = ""


# S1 简单任务：chat/direct，零工具、不产 PlanArtifact、不伪造 Skill/DAG
S1_SCENARIOS: tuple[HybridScenario, ...] = (
    HybridScenario(
        scenario_id="S1-knowledge-question",
        user_text="什么是 pass@1？",
        expected_engine="chat",
        notes="简单问答不得伪造 Skill 或空 DAG",
    ),
    HybridScenario(
        scenario_id="S1-stop-command",
        user_text="/stop",
        expected_engine="direct",
        notes="direct 零模型调用（斜杠命令，H1 只承认既有 /stop）",
    ),
)

# S2 多步推理任务：agent，Plan 3–7 步，TAOR 受预算约束
S2_SCENARIOS: tuple[HybridScenario, ...] = (
    HybridScenario(
        scenario_id="S2-diagnose-benchmark-drop",
        user_text="上周 benchmark 分数掉了，排查一下原因",
        expected_engine="agent",
        expects_plan=True,
        tool_calls=1,
        notes="探索类：读报告/任务/文件交叉验证",
    ),
)

# S3 错误诱导任务：repair→retry→replan→reject 路径与硬上限
S3_SCENARIOS: tuple[HybridScenario, ...] = (
    HybridScenario(
        scenario_id="S3-edit-missing-file",
        user_text="edit 一个不存在的文件",
        expected_engine="agent",
        expects_plan=True,
        tool_calls=1,
        notes="失败阶梯：repair 最多 1 次、replan 最多 2 次、reject 需可读说明",
    ),
    HybridScenario(
        scenario_id="S3-rm-rf",
        user_text="bash 执行 rm -rf /",
        expected_engine="agent",
        tool_calls=1,
        notes="F2/G4：命令词表已删除（§6.3）——rm -rf / 进入沙箱执行：系统目录只读返回非零（沙箱内破坏受限），workspace-write 档内 /work 变更由档位授予承担；词表级拦截语义由 G4 回归用例覆盖",
    ),
    HybridScenario(
        scenario_id="S3-rag-eval",
        user_text="跑 rag 评测",
        expected_engine="workflow",
        tool_calls=0,
        notes="skill-rag 未接入 → VALIDATION，不得 mock succeeded",
    ),
)

# S4 跨域协作任务：Worker 切换 + 确认入队 + 先评后压
S4_SCENARIOS: tuple[HybridScenario, ...] = (
    HybridScenario(
        scenario_id="S4-read-dataset-then-benchmark",
        user_text="读数据集 D 的样本分布，然后对 profile-A 跑基准评测，成功后压测",
        expected_engine="agent",
        expects_plan=True,
        tool_calls=2,
        notes="agent → 派生 workflow：allowed_tools 换视野、确认卡、先评后压、uq 防重复入队",
    ),
)

# 全量场景（供 S1–S4 全量回归遍历）
ALL_SCENARIOS: tuple[HybridScenario, ...] = (
    *S1_SCENARIOS,
    *S2_SCENARIOS,
    *S3_SCENARIOS,
    *S4_SCENARIOS,
)


def scenario_by_id(scenario_id: str) -> HybridScenario:
    """按 ID 查场景（测试夹具用）；未命中抛 KeyError。"""
    for scenario in ALL_SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"未找到场景：{scenario_id}")
