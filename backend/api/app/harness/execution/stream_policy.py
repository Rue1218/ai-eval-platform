"""内容块交错流的协议档灰度策略（P4）。

并行必须同时满足：总开关、进程内未脚踢、显式批次、协议档白名单。
白名单为空表示不开任何协议档；``*`` 表示全部 native 协议档。
P1 首轮流式默认对所有 native 开放，可用总开关或白名单收窄/回滚。
"""

from __future__ import annotations

from collections.abc import Mapping

PROFILE_ID_WILDCARD = "*"


def parse_profile_ids(raw: str | None) -> frozenset[str]:
    """把逗号分隔的协议档 ID 解析为集合；忽略空白。"""
    return frozenset(part.strip() for part in str(raw or "").split(",") if part.strip())


def profile_id_from_configurable(configurable: Mapping[str, object] | None) -> str:
    """从 RunnableConfig.configurable.profile.id 读取当前 Agent 协议档。"""
    if not isinstance(configurable, Mapping):
        return ""
    profile = configurable.get("profile")
    if not isinstance(profile, Mapping):
        return ""
    return str(profile.get("id") or "").strip()


def _profile_allowed(profile_id: str, raw_allowlist: str, *, empty_means_all: bool) -> bool:
    """白名单判定。empty_means_all 用于 P1（已全量）与 P3 并行（默认无人）。"""
    allowed = parse_profile_ids(raw_allowlist)
    if not allowed:
        return empty_means_all
    if PROFILE_ID_WILDCARD in allowed:
        return True
    return bool(profile_id) and profile_id in allowed


def native_stream_allowed(profile_id: str | None, tool_call_mode: str) -> bool:
    """P1：native 协议档是否走 gateway.stream()。legacy 永远否。"""
    if str(tool_call_mode or "") != "native":
        return False
    from app.config import settings

    if not bool(settings.agent_native_stream_enabled):
        return False
    return _profile_allowed(
        str(profile_id or "").strip(),
        settings.agent_native_stream_profile_ids,
        empty_means_all=True,
    )


def parallel_batch_allowed(profile_id: str | None, *, has_batch: bool) -> bool:
    """P3/P4：是否允许本回合只读 ToolBatch 并行。"""
    if not has_batch:
        return False
    from app.config import settings

    if not bool(settings.agent_parallel_tool_batch_enabled):
        return False
    from .stream_metrics import get_default_stream_metrics

    if get_default_stream_metrics().is_parallel_disabled():
        return False
    return _profile_allowed(
        str(profile_id or "").strip(),
        settings.agent_parallel_tool_batch_profile_ids,
        empty_means_all=False,
    )
