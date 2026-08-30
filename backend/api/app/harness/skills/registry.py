"""Harness 技能体系：技能目录与启用门禁（M10 阶段 4，SK-4/SK-5）。

``SKILL_CATALOG`` 为技能目录单一事实源（前端 ``skillLabels.ts`` 同源对齐，
非同步副本）；``DISABLED_SKILLS`` 为未接入技能集（LightRAG 未接入时
``rag`` 必须失败，禁止 mock succeeded，SK-4/MEM-5）。``list_hints`` 返回
全部 SkillHint（M7 晚波契约）供 M4 路由注入；完整工作流见 ``workflows.py``。
"""

from __future__ import annotations

from collections.abc import Mapping

from app.errors import AppError, ErrorCode
from app.harness.contracts import SkillHint
from app.harness.skills.storage import RUNTIME_DISABLED_SKILLS, list_skill_metadata

# 技能目录（单一事实源；skill_id → (名称, 一句话描述, kind)）
SKILL_CATALOG: dict[str, tuple[str, str, str]] = {
    "skill-benchmark": ("基准评测", "执行大模型基准评测", "benchmark"),
    "skill-testcase": ("用例生成", "生成评测测试用例", "testcase"),
    "skill-rag": ("知识库评测", "执行知识库评测", "rag"),
    "skill-stress": ("压测", "执行共享压测", "stress"),
}

# 未接入技能（LightRAG 未接入 → rag 必须失败；禁止 mock succeeded）
DISABLED_SKILLS: frozenset[str] = RUNTIME_DISABLED_SKILLS


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


def get_hint(skill_id: str) -> SkillHint:
    """取单个 SkillHint；未注册抛 AppError(VALIDATION)。"""
    entry = SKILL_CATALOG.get(skill_id)
    if entry is None:
        raise AppError(ErrorCode.VALIDATION, f"未知技能：{skill_id}")
    return SkillHint(skill_id=skill_id, name=entry[0], summary=entry[1])


def list_hints() -> list[SkillHint]:
    """返回全部 SkillHint（M7 晚波契约），供 M4 路由注入与
    前端 ``skillLabels.ts`` 对齐（SK-5）。"""
    # 仅读取每个 SKILL.md 的固定头部，禁止在技能目录阶段加载工作流正文。
    metadata_by_id = {metadata.skill_id: metadata for metadata in list_skill_metadata()}
    hints: list[SkillHint] = []
    for skill_id, entry in SKILL_CATALOG.items():
        metadata = metadata_by_id.get(skill_id)
        hints.append(
            SkillHint(
                skill_id=skill_id,
                name=metadata.name if metadata else entry[0],
                summary=metadata.summary if metadata else entry[1],
            )
        )
    return hints


def plan_skill_id(state: Mapping[str, object] | None) -> str | None:
    """从 GraphState.plan 取本轮 skill_id 索引；空串视为未选中。

    只返回索引，不返回工作流正文（Progressive Disclosure / SK-1）。
    """
    if not isinstance(state, Mapping):
        return None
    plan = state.get("plan")
    if not isinstance(plan, Mapping):
        return None
    raw = plan.get("skill_id")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None
