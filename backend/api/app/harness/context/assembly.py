"""Harness 上下文工程层：上下文装配 + 按需工具注入（M2 阶段 1/2，CX-4/CX-5）。

装配顺序固定：Persona → Skill Hint → 摘要 → 阶段输入 → 用户消息（CX-4）。
工具定义按本轮能力最小注入（CX-5）：未注册工具不注入、本轮未选工具不注入；
阶段 1 Chat 路径不注入工具定义。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def assemble(
    *,
    system: str,  # Persona（M1 build_system_prompt 产出）
    skill_hints: Sequence[str] | None = None,
    summary: str | None = None,  # compact 摘要（compact.py 产出，可选）
    stage_input: str | None = None,  # 当前阶段协议说明（M4 节点提供）
    messages: list[Mapping[str, object]],  # window.py 产出
    tool_defs: Sequence[Mapping[str, object]] | None = None,  # 按本轮最小注入
) -> dict:
    """按固定顺序装配模型本轮输入（CX-4）：
    Persona → Skill Hint → 摘要 → 阶段输入 → 用户消息。

    返回 {'system': str, 'messages': list, 'tools': list} 供 ModelRequest 构造。
    """
    sections: list[str] = [system]
    if skill_hints:
        sections.append("【可见技能】\n" + "\n".join(f"- {hint}" for hint in skill_hints))
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
) -> list[Mapping[str, object]]:
    """按本轮 mode 与 tools_needed 从注册表取工具定义（CX-5）。

    未注册不返回；Chat 路径返回空（阶段 1 不注入工具定义）。阶段 2 起注册表
    提供 ``get_def(name)`` 查询接口。
    """
    if mode != "react":
        return []
    get_def = getattr(registry, "get_def", None)
    if get_def is None:
        return []
    definitions: list[Mapping[str, object]] = []
    for name in tools_needed:
        definition = get_def(name)
        if definition is not None:
            definitions.append(definition)
    return definitions
