"""跨层 artifact 契约（M7 阶段 2 早波 + 阶段 4 晚波）。

早波（ToolCall/ToolResult/Observation）供执行层 M5 / 反馈层 M6 / 上下文层 M2
消费；晚波（PlanArtifact/SkillHint）供编排层 M4 / 技能体系 M10 消费。

全部契约 frozen + JSON 可序列化（PG 检查点兼容），禁止嵌 Callable、
WebSocket、DB Session；提供 to_dict / from_dict 往返与最小校验。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeVar, cast

# —— 阶段 4 晚波 ——


@dataclass(frozen=True, slots=True)
class SkillHint:
    """技能名称 + 一句话描述（SK-1），常驻提示不常驻正文。"""

    skill_id: str  # 如 "skill-benchmark"
    name: str  # 显示名
    summary: str  # 一句话描述


@dataclass(frozen=True, slots=True)
class PlanArtifact:
    """规划产物（OR-2 冻结字段，含 allows_replan）。"""

    intent: str  # 意图
    skill_id: str | None  # 关联技能
    slots: Mapping[str, object]  # 槽位
    tools_needed: tuple[str, ...]  # 需要的工具名
    delivery: Literal["chat", "confirm"]  # 交付方式
    budget: Mapping[str, int]  # 次数预算（count-only：model_calls/tool_turns 整数，不含 token 预算）
    allows_replan: bool  # 是否允许补规划
    notes: str = ""


# —— 阶段 2 早波 ——


@dataclass(frozen=True, slots=True)
class ToolCall:
    """工具调用契约（对齐 API.md tool_call 事件 payload）。"""

    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具结果契约（对齐 API.md tool_result 事件 payload）。"""

    name: str
    ok: bool
    data: Mapping[str, object] = field(default_factory=dict)
    error: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Observation:
    """工具结果归一（FB-1），带脱敏/截断/来源标记。"""

    tool: str
    text: str  # 脱敏 + 截断后的摘要
    ok: bool
    truncated: bool = False
    source: str | None = None  # 溯源标识，复用 messages 表 source_id 格式（如 "file:uuid" / "message:uuid"）
    redacted: bool = True  # 默认已脱敏
    arguments: Mapping[str, object] | None = None  # 本次调用参数（OR-4 防重复判断用）


T = TypeVar("T")


def to_dict(obj: object) -> dict:
    """把 frozen dataclass 契约转为纯 dict（json.dumps 安全）。"""
    return {field_.name: _plain(getattr(obj, field_.name)) for field_ in obj.__dataclass_fields__.values()}  # type: ignore[attr-defined]


def _plain(value: object) -> object:
    """递归把 tuple / Mapping 转为 json.dumps 安全的纯 dict/list。"""
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def from_dict(cls: type[T], data: dict) -> T:
    """从 dict 重建契约；字段缺失/多余抛 ValueError。"""
    expected = set(getattr(cls, "__dataclass_fields__", {}).keys())
    actual = set(data.keys())
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{cls.__name__} 字段不匹配 missing={missing} extra={extra}")
    kwargs: dict[str, object] = {}
    for name in expected:
        value = data[name]
        if name in {"tools_needed"}:
            kwargs[name] = tuple(value)
        else:
            kwargs[name] = value
    return cast(T, cls(**kwargs))


def validate_plan_artifact(data: dict) -> PlanArtifact:
    """PlanArtifact schema 校验：拒绝缺字段/多字段（C-A5）。"""
    return from_dict(PlanArtifact, data)
