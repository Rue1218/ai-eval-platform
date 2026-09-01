"""Harness 上下文工程层：上下文装配 + 按需工具注入（M2 阶段 1/2，CX-4/CX-5）。

装配顺序固定：Persona → Skill Hint → 技能工作流（可选）→ 摘要 → 阶段输入
→ 用户消息（CX-4 / SK-1）。工具定义按本轮能力最小注入（CX-5）：Chat/Direct
不注入；ReAct 注入已注册的短原生工具，并并入 ``tools_needed`` 中已注册项；
未注册与未点名的 MCP 长工具不默认注入。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def skill_hints_for_turn(skill_id: str | None = None) -> list[str]:
    """本轮 Skill Hint 行（SK-1/SK-2）。

    未选中技能时注入常驻四条目录；已选中时只注入当前 Hint，避免把历史技能卡
    或其它技能正文带进本轮。完整工作流走 ``load_skill_workflow``，不在此展开。
    """
    from app.harness.skills import get_hint, list_hints

    if skill_id:
        hint = get_hint(skill_id)
        return [f"{hint.name}：{hint.summary}"]
    return [f"{hint.name}：{hint.summary}" for hint in list_hints()]


def skill_hint_lines() -> list[str]:
    """常驻 Skill Hint 目录（SK-1）；不含完整工作流正文。"""
    return skill_hints_for_turn(None)


def compact_summary_from_configurable(
    configurable: Mapping[str, object] | None,
) -> str | None:
    """从 RunnableConfig.configurable.session 读取 compact 摘要（可空）。"""
    session = (configurable or {}).get("session") if isinstance(configurable, Mapping) else None
    if not isinstance(session, Mapping):
        return None
    summary = str(session.get("compact_summary") or "").strip()
    return summary or None


def assemble(
    *,
    system: str,  # Persona（M1 build_system_prompt 产出）
    skill_hints: Sequence[str] | None = None,
    skill_workflow: str | None = None,  # 本轮按需工作流（SK-1，可选）
    summary: str | None = None,  # compact 摘要（compact.py 产出，可选）
    stage_input: str | None = None,  # 当前阶段协议说明（M4 节点提供）
    messages: list[Mapping[str, object]],  # window.py 产出
    tool_defs: Sequence[Mapping[str, object]] | None = None,  # 按本轮最小注入
) -> dict:
    """按固定顺序装配模型本轮输入（CX-4）：
    Persona → Skill Hint → 技能工作流 → 摘要 → 阶段输入 → 用户消息。

    ``skill_workflow`` 仅本轮选中技能时注入，不写入 GraphState（SK-1/SK-2）。
    返回 {'system': str, 'messages': list, 'tools': list} 供 ModelRequest 构造。
    """
    sections: list[str] = [system]
    if skill_hints:
        sections.append("【可见技能】\n" + "\n".join(f"- {hint}" for hint in skill_hints))
    if skill_workflow:
        sections.append("【当前技能工作流】\n" + skill_workflow)
    if summary:
        sections.append("【会话摘要】\n" + summary)
    if stage_input:
        sections.append("【当前阶段】\n" + stage_input)
    return {
        "system": "\n\n".join(sections),
        "messages": [dict(message) for message in messages],
        "tools": [dict(tool) for tool in (tool_defs or [])],
    }


def select_tool_defs(
    registry: object,  # M5 registry.py（阶段 2 提供；duck typing，不强制 import）
    *,
    mode: str,
    tools_needed: tuple[str, ...] = (),
    planned_only: bool = False,
) -> list[Mapping[str, object]]:
    """按本轮 mode 与 tools_needed 从注册表取工具定义（CX-5）。

    Chat/Direct 返回空。无计划的 ReAct 默认注入 ``transport=native`` 短工具
    （本轮执行能力），并并入 ``tools_needed`` 中已注册项。有 ``PlanArtifact``
    时 ``planned_only=True``：执行器只看见计划剩余工具，避免确认卡路径把
    全量原生工具重新铺开造成空转循环。未注册不返回；MCP 长工具
    （如 ``task.create``）不默认注入。无 ``iter_defs`` 的测试桩仅消费
    ``tools_needed``。
    """
    if mode != "react":
        return []
    get_def = getattr(registry, "get_def", None)
    if get_def is None:
        return []
    names: list[str] = []
    iter_defs = getattr(registry, "iter_defs", None)
    if callable(iter_defs) and not planned_only:
        names.extend(definition.name for definition in iter_defs(transport="native"))
    for name in tools_needed:
        if name and name not in names:
            names.append(name)
    definitions: list[Mapping[str, object]] = []
    for name in names:
        definition = get_def(name)
        if definition is not None:
            definitions.append(definition)
    return definitions
