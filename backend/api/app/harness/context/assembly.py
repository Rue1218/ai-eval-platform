"""Harness 上下文工程层：上下文装配 + 按需工具注入（M2 阶段 1/2，CX-4/CX-5）。

装配顺序固定：Persona → Skill Hint → 技能工作流（可选）→ 摘要 → 阶段输入
→ 用户消息（CX-4 / SK-1）。工具定义按本轮能力最小注入（CX-5）：Chat/Direct
不注入；ReAct 注入已注册的短原生工具，并并入 ``tools_needed`` 中已注册项；
未注册与未点名的 MCP 长工具不默认注入。

H0（混合驱动引擎基础设施）：新增 ``assemble_segments`` 提供 ADR-5 缓存边界的
分段装配（静态段在前、动态段在后，段序单调）。``assemble`` 保持原签名与
返回结构不变，内部委托分段渲染，保证 ``prompt_cache_enabled=False`` 时输出
与骨架化版本**字节级一致**。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


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


# ─── 缓存边界分段（ADR-5 / H0）───

# 段序标识：静态在前（global/skill），动态在后（session/none），严格单调。
# 与 ADR-5 的 S1–S7 对应：S1 Persona/L2 项目指令、S2 Skill Hint、S3 工具
# 定义（tools payload 承载，不入 system 文本）、S4 Skill 工作流正文、S5
# 会话负责人/协议档 Overlay、S6 会话摘要、S7 阶段输入/当轮动态（不缓存）。
SEGMENT_S1_PERSONA = 1
SEGMENT_S2_SKILL_HINTS = 2
SEGMENT_S4_SKILL_WORKFLOW = 4
SEGMENT_S5_OVERLAY = 5
SEGMENT_S6_SUMMARY = 6
SEGMENT_S7_STAGE = 7


@dataclass(frozen=True, slots=True)
class PromptSegment:
    """装配产出的提示词分段（缓存边界最小单元）。

    ``order`` 为段序（单调递增，装配层强制）；``cacheable`` 标记静态可缓存
    段（global/skill 级），适配器仅在最后一个可缓存段后打缓存断点。
    """

    text: str
    order: int
    cacheable: bool = False


def _segment(text: str, order: int, *, cacheable: bool) -> PromptSegment:
    """构造非空分段；空文本直接剔除（与 ``assemble`` 的空段省略语义一致）。"""
    return PromptSegment(text=text, order=order, cacheable=cacheable)


def assemble_segments(
    *,
    system: str,  # Persona（M1 build_system_prompt 产出；含五段策略与受控槽）
    skill_hints: Sequence[str] | None = None,
    skill_workflow: str | None = None,  # 本轮按需工作流（SK-1，可选）
    overlay: str | None = None,  # 会话负责人 + 协议档补充提示词（动态 S5）
    summary: str | None = None,  # compact 摘要（compact.py 产出，可选）
    stage_input: str | None = None,  # 当前阶段协议说明（M4 节点提供，可选）
) -> tuple[PromptSegment, ...]:
    """按 ADR-5 段序产出带缓存边界的分段（静态在前、动态在后）。

    - S1 Persona 与 S2 Skill Hint：部署级静态，``cacheable=True``；
    - S4 Skill 工作流正文：技能级静态（按 skill_id 分桶），``cacheable=True``；
    - S5 Overlay、S6 会话摘要与 S7 阶段输入：会话/当轮动态，``cacheable=False``；
    - 空的可选段不产出（与 ``assemble`` 空段省略语义一致）。

    渲染顺序由 ``assemble`` 强制为分段序，禁止调用方调整——缓存断点落在
    最后一个可缓存段之后，一旦动态段插入静态前缀，整个前缀缓存即失效。
    """
    segments: list[PromptSegment] = [_segment(system, SEGMENT_S1_PERSONA, cacheable=True)]
    if skill_hints:
        segments.append(
            _segment(
                "【可见技能】\n" + "\n".join(f"- {hint}" for hint in skill_hints),
                SEGMENT_S2_SKILL_HINTS,
                cacheable=True,
            )
        )
    if skill_workflow:
        segments.append(
            _segment(
                "【当前技能工作流】\n" + skill_workflow,
                SEGMENT_S4_SKILL_WORKFLOW,
                cacheable=True,
            )
        )
    if overlay:
        segments.append(_segment(overlay, SEGMENT_S5_OVERLAY, cacheable=False))
    if summary:
        segments.append(
            _segment("【会话摘要】\n" + summary, SEGMENT_S6_SUMMARY, cacheable=False)
        )
    if stage_input:
        segments.append(
            _segment("【当前阶段】\n" + stage_input, SEGMENT_S7_STAGE, cacheable=False)
        )
    return tuple(segments)


def _render_system(segments: Sequence[PromptSegment]) -> str:
    """按段序渲染为单块 system 字符串（与骨架化 ``assemble`` 的 join 字节级一致）。"""
    return "\n\n".join(segment.text for segment in segments)


def assemble(
    *,
    system: str,  # Persona（M1 build_system_prompt 产出）
    skill_hints: Sequence[str] | None = None,
    skill_workflow: str | None = None,  # 本轮按需工作流（SK-1，可选）
    overlay: str | None = None,  # 会话负责人 + 协议档补充提示词（动态 S5）
    summary: str | None = None,  # compact 摘要（compact.py 产出，可选）
    stage_input: str | None = None,  # 当前阶段协议说明（M4 节点提供）
    messages: list[Mapping[str, object]],  # window.py 产出
    tool_defs: Sequence[Mapping[str, object]] | None = None,  # 按本轮最小注入
) -> dict:
    """按固定顺序装配模型本轮输入（CX-4）：
    Persona → Skill Hint → 技能工作流 → Overlay → 摘要 → 阶段输入 → 用户消息。

    ``skill_workflow`` 仅本轮选中技能时注入，不写入 GraphState（SK-1/SK-2）。
    返回 {'system': str, 'messages': list, 'tools': list} 供 ModelRequest 构造。

    H0 起内部委托 ``assemble_segments`` 渲染 system：段序单调由装配层强制，
    但本函数仍返回单块字符串（``prompt_cache_enabled=False`` 时字节级兼容）；
    启用缓存的路径请直接使用 ``assemble_segments`` 并把分段挂到 ModelRequest。
    """
    segments = assemble_segments(
        system=system,
        skill_hints=skill_hints,
        skill_workflow=skill_workflow,
        overlay=overlay,
        summary=summary,
        stage_input=stage_input,
    )
    return {
        "system": _render_system(segments),
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
