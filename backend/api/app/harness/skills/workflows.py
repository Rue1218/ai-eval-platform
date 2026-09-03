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


def extract_skill_examples(skill_id: str) -> str:
    """读取 SKILL.md 正文中的 ``## 示例请求`` 段（O1 路由语料单一来源）。

    落法裁决（混合驱动引擎架构 V1.4 §5.7.2）：示例段是正文的第二个二级段落，
    放在 ``## 工作流`` **之后**——头部保持严格六键不变（``_parse_header``
    零改动），且与工作流正文同文件同修订指纹，改 Skill 时示例就在眼前，
    消除 Router 关键词表与 Skill 描述的知识漂移。返回段落正文（不含标题），
    未书写示例段时返回空串。本函数仅供路由侧做向量/关键词语料，**不进入**
    运行时提示词装配（正文仍经 ``load_skill_workflow`` 渐进披露）。
    """
    workflow = load_skill_workflow(skill_id)  # 含 assert_skill_enabled 门禁
    marker = "## 示例请求"
    position = workflow.find(marker)
    if position < 0:
        return ""
    section = workflow[position + len(marker):]
    end = section.find("\n## ", 1)
    return section[:end].strip() if end >= 0 else section.strip()
