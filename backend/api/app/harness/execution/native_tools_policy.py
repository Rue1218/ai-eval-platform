"""原生协议工具装配许可与档级熔断（F0/P1，《Agent 原生工具装配方案》V0.2）。

装配三态许可（D5 修订）：
- 主闸门 ``settings.agent_native_tools_enabled``（默认关 = 请求逐字节不带
  tools，行为零变化）；
- per-profile 显式清单 ``settings.agent_native_tools_profile_ids``：空 = 不
  开任何档；``*`` = 全部；否则仅列出的协议档 ID（语义与 stream 白名单
  stream_policy 一致，但独立字段——stream 与 tools 是不同放行面，待决点 5）；
- 进程内档级熔断：带 tools 请求连续失败（含端点 400/超时等 AppError）达
  ``circuit_failure_threshold`` 次 → 该档摘除 tools 装配（native_tools_allowed
  返回 False），冷却 ``circuit_cooldown_s`` 后自动恢复探测一次（半开语义：
  成功即清零，失败重新计数）。

``tool_call_mode`` 不担任装配许可：生产默认值已为 native（迁移
a9c41b7e2d10），若以其为许可则主闸门一开即全协议档全量下发（V0.2 B2
评审结论）。本模块是装配许可的唯一消费点。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping

from .stream_policy import PROFILE_ID_WILDCARD, parse_profile_ids

logger = logging.getLogger("ai-eval.agent")

_BREAKER_LOCK = threading.Lock()
# profile_id -> {"fails": int, "open_until": float}
_BREAKER: dict[str, dict[str, float | int]] = {}


def _breaker_state(profile_id: str) -> dict[str, float | int]:
    state = _BREAKER.get(profile_id)
    if state is None:
        state = {"fails": 0, "open_until": 0.0}
        _BREAKER[profile_id] = state
    return state


def _breaker_open(profile_id: str) -> bool:
    """熔断 open 判定；到期后自动转半开（重置 open_until，放行一次探测）。"""
    now = time.monotonic()
    with _BREAKER_LOCK:
        state = _breaker_state(profile_id)
        until = float(state.get("open_until") or 0.0)
        if until and now < until:
            return True
        if until and now >= until:  # 冷却到期：半开探测（fail 计数已清零）
            state["open_until"] = 0
            logger.info("native_tools_breaker_halfopen profile=%s", profile_id)
        return False


def native_tools_allowed(profile_id: str | None) -> bool:
    """当前协议档是否装配原生 tools（主闸门 × 白名单 × 熔断，全部满足才放行）。"""
    from app.config import settings

    if not bool(settings.agent_native_tools_enabled):
        return False
    allowed = parse_profile_ids(settings.agent_native_tools_profile_ids)
    if not allowed:
        return False
    pid = str(profile_id or "").strip()
    if PROFILE_ID_WILDCARD not in allowed and (not pid or pid not in allowed):
        return False
    return not _breaker_open(pid)


def native_tools_report_failure(profile_id: str | None) -> None:
    """带 tools 请求失败上报：连续达阈值即熔断 open（摘除该档装配）。

    熔断为运维可观测事件：open/半开分别记 warning/info 日志（冒烟清单据此
    验证档级摘除与自动恢复）。
    """
    from app.config import settings

    pid = str(profile_id or "").strip()
    threshold = int(settings.circuit_failure_threshold)
    cooldown_s = float(settings.circuit_cooldown_s)
    with _BREAKER_LOCK:
        state = _breaker_state(pid)
        fails = int(state.get("fails") or 0) + 1
        if fails >= threshold:
            state["fails"] = 0
            state["open_until"] = time.monotonic() + cooldown_s
            logger.warning(
                "native_tools_breaker_open profile=%s after %d failures（该档 tools 装配已摘除，cooldown=%ss）",
                pid,
                threshold,
                cooldown_s,
            )
        else:
            state["fails"] = fails


def native_tools_report_success(profile_id: str | None) -> None:
    """带 tools 请求成功：连续失败计数清零（closed/半开探测成功同语义）。"""
    with _BREAKER_LOCK:
        _breaker_state(str(profile_id or "").strip())["fails"] = 0


def native_tools_breaker_reset() -> None:
    """清空熔断状态（仅测试用；生产不调用）。"""
    with _BREAKER_LOCK:
        _BREAKER.clear()


def native_tools_breaker_snapshot() -> Mapping[str, dict[str, float | int]]:
    """返回熔断状态快照（仅测试断言用；生产不依赖）。"""
    with _BREAKER_LOCK:
        return {key: dict(value) for key, value in _BREAKER.items()}
