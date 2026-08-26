"""Harness 技能体系：完整工作流正文（M10 SK-1 Progressive Disclosure）。

Skill Hint（名称 + 一句话）常驻目录；完整工作流**不进 GraphState**，由节点
按本轮 ``plan.skill_id`` 按需 ``load_skill_workflow`` 装配进上下文。未接入
技能（``DISABLED_SKILLS``）禁止返回正文，一律 ``VALIDATION``。
"""

from __future__ import annotations

from app.errors import AppError, ErrorCode
from app.harness.skills.registry import assert_skill_enabled

# 启用技能的完整工作流（评测执行细节）。不含 skill-rag：未接入不得加载正文。
SKILL_WORKFLOWS: dict[str, str] = {
    "skill-benchmark": (
        "1. 确认协议档、数据集与评测模型槽位；缺槽发确认卡，不得直接入队。\n"
        "2. 确认卡 kind=benchmark；sample_size 默认 1000。\n"
        "3. 用户确认后由 Worker 执行三协议调用、规则评分、预算熔断、断点续跑。\n"
        "4. 对话内禁止同步跑完评测，禁止伪造 succeeded。"
    ),
    "skill-testcase": (
        "1. 确认协议档与生成策略槽位；缺槽发确认卡。\n"
        "2. 确认卡 kind=testcase；六策略 LLM 生成、72h 确认超时扫描。\n"
        "3. 不得在对话进程内同步生成完整用例集。"
    ),
    "skill-stress": (
        "1. 对话路径不得发 kind=stress 确认卡。\n"
        "2. 压测仅在质量任务 succeeded 且 with_stress=true 时由系统派生。\n"
        "3. 用户口头要求压测时，应引导先完成质量评测（先评后压）。"
    ),
}


def load_skill_workflow(skill_id: str) -> str:
    """按需加载完整工作流正文（SK-1）；未启用 / 未注册抛 VALIDATION。

    调用方只把返回文本写入本轮 ``assemble``，禁止写入 GraphState。
    """
    assert_skill_enabled(skill_id)
    body = SKILL_WORKFLOWS.get(skill_id)
    if not body:
        raise AppError(ErrorCode.VALIDATION, f"未知技能：{skill_id}")
    return body
