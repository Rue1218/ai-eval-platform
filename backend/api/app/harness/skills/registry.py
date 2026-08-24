"""Harness 技能体系：技能目录与启用门禁（M10 阶段 4，SK-4/SK-5）。

``SKILL_CATALOG`` 为技能目录单一事实源（`/api/slash-commands` 同源引用，
非同步副本）；``DISABLED_SKILLS`` 为未接入技能集（LightRAG 未接入时
``rag`` 必须失败，禁止 mock succeeded，SK-4/MEM-5）。``list_hints`` 返回
全部 SkillHint（M7 晚波契约）供 M4 路由注入。
"""

from __future__ import annotations

from app.errors import AppError, ErrorCode
from app.harness.contracts import SkillHint

# 技能目录（单一事实源；skill_id → (名称, 一句话描述, kind)）
SKILL_CATALOG: dict[str, tuple[str, str, str]] = {
    "skill-benchmark": ("基准评测", "执行大模型基准评测", "benchmark"),
    "skill-testcase": ("用例生成", "生成评测测试用例", "testcase"),
    "skill-rag": ("知识库评测", "执行知识库评测", "rag"),
    "skill-stress": ("压测", "执行共享压测", "stress"),
}

# 未接入技能（LightRAG 未接入 → rag 必须失败；禁止 mock succeeded）
DISABLED_SKILLS: frozenset[str] = frozenset({"skill-rag"})


def skill_to_kind(skill_id: str) -> str:
    """skill_id → kind 映射；未映射抛 AppError(VALIDATION)。"""
    entry = SKILL_CATALOG.get(skill_id)
    if entry is None:
        raise AppError(ErrorCode.VALIDATION, f"未知技能：{skill_id}")
    return entry[2]


def assert_skill_enabled(skill_id: str) -> None:
    """未接入 skill 抛 AppError(VALIDATION, "技能未启用")；禁止 mock succeeded。"""
    if skill_id not in SKILL_CATALOG:
        raise AppError(ErrorCode.VALIDATION, f"未知技能：{skill_id}")
    if skill_id in DISABLED_SKILLS:
        raise AppError(ErrorCode.VALIDATION, "技能未启用")


def list_hints() -> list[SkillHint]:
    """返回全部 SkillHint（M7 晚波契约），供 M4 路由注入与
    `/api/slash-commands` 对齐（SK-5）。"""
    return [
        SkillHint(skill_id=skill_id, name=entry[0], summary=entry[1])
        for skill_id, entry in SKILL_CATALOG.items()
    ]
