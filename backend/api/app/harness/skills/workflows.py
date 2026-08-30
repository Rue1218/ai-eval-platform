"""Harness 技能体系：完整工作流正文（M10 SK-1 Progressive Disclosure）。

Skill Hint（名称 + 一句话）常驻目录；完整工作流**不进 GraphState**，由节点
按本轮 ``plan.skill_id`` 按需 ``load_skill_workflow`` 装配进上下文。未接入
技能（``DISABLED_SKILLS``）禁止返回正文，一律 ``VALIDATION``。
"""

from __future__ import annotations

from app.harness.skills.registry import assert_skill_enabled
from app.harness.skills.storage import load_skill_workflow_file


def load_skill_workflow(skill_id: str) -> str:
    """按需加载完整工作流正文（SK-1）；未启用 / 未注册抛 VALIDATION。

    调用方只把返回文本写入本轮 ``assemble``，禁止写入 GraphState。
    """
    assert_skill_enabled(skill_id)
    return load_skill_workflow_file(skill_id)
