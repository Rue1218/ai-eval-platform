"""回合预算：键名对齐架构 §3.2.2，缺省必须是产品常量而非架构表示例。"""

from __future__ import annotations

import os

from app.agent.defaults import DEFAULT_TOOL_ROUNDS, HARD_MAX_TOOL_ROUNDS, TURN_WALL_CLOCK_S
from app.harness.contracts.cancellation import DEFAULT_PROPAGATION_BUDGET_MS

# 诊断保留天数常量；定时清理任务可后补，本阶段只提供表字段 + 该默认值。
DIAGNOSTICS_RETENTION_DAYS_DEFAULT = 30


def _env_int(name: str) -> int | None:
    """读取整型环境变量；未设置或空白视为未启用。"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def max_react_steps() -> int:
    """单回合最大工具/推理轮次硬顶。未设 env 时为产品硬顶 5。"""
    value = _env_int("HARNESS_MAX_REACT_STEPS")
    if value is None:
        return HARD_MAX_TOOL_ROUNDS
    return max(1, value)


def turn_deadline_s() -> float:
    """单回合墙钟（秒）。未设 env 时为产品 180s，禁止默认成架构表示例 60。"""
    value = _env_int("HARNESS_TURN_DEADLINE_S")
    if value is None:
        return float(TURN_WALL_CLOCK_S)
    return float(max(1, value))


def rounds_cap(max_tool_rounds: int | None) -> int:
    """规划轮次与硬顶取小。"""
    value = int(max_tool_rounds or DEFAULT_TOOL_ROUNDS)
    return min(value, max_react_steps())


def wall_clock_s() -> float:
    """供总控 wait_for 使用的墙钟。"""
    return turn_deadline_s()


def same_call_fingerprint_cap() -> int | None:
    """同 tool+规范化 arguments 重复上限。未设 env 返回 None，不改现网去重。"""
    value = _env_int("HARNESS_MAX_SAME_CALL_FINGERPRINT")
    return max(1, value) if value is not None else None


def consecutive_retryable_error_cap() -> int | None:
    """连续可重试错误上限。未设 env 则不截断。"""
    value = _env_int("HARNESS_MAX_CONSECUTIVE_RETRYABLE_ERROR")
    return max(1, value) if value is not None else None


def max_context_rebuilds() -> int | None:
    """同一回合上下文重建次数上限。阶段 2 只读配置，阶段 4 接线后才截断。"""
    value = _env_int("HARNESS_MAX_CONTEXT_REBUILDS")
    return max(0, value) if value is not None else None


def max_parallel_calls() -> int:
    """单批次并行上限；阶段 3 才使用。未设 env 时为 4。"""
    value = _env_int("HARNESS_MAX_PARALLEL_CALLS")
    return max(1, value) if value is not None else 4


def cancel_propagation_budget_ms() -> int:
    """本地取消调度 SLO（毫秒）。"""
    value = _env_int("HARNESS_CANCEL_PROPAGATION_BUDGET_MS")
    return max(1, value) if value is not None else DEFAULT_PROPAGATION_BUDGET_MS


def diagnostics_retention_days() -> int:
    """诊断记录保留天数；定时 job 可后补。"""
    value = _env_int("HARNESS_DIAGNOSTICS_RETENTION_DAYS")
    return max(1, value) if value is not None else DIAGNOSTICS_RETENTION_DAYS_DEFAULT


def echo_budget_config() -> None:
    """启动时回显生效值，禁止打印密钥。"""
    from app.agent.log import agent_trace

    fingerprint = same_call_fingerprint_cap()
    retryable = consecutive_retryable_error_cap()
    rebuilds = max_context_rebuilds()
    agent_trace(
        "Harness 预算 "
        f"max_react_steps={max_react_steps()} "
        f"turn_deadline_s={turn_deadline_s()} "
        f"default_rounds={DEFAULT_TOOL_ROUNDS} "
        f"fingerprint={'未启用' if fingerprint is None else fingerprint} "
        f"consecutive_retryable={'未启用' if retryable is None else retryable} "
        f"context_rebuilds={'未启用' if rebuilds is None else rebuilds} "
        f"max_parallel_calls={max_parallel_calls()} "
        f"cancel_budget_ms={cancel_propagation_budget_ms()} "
        f"diagnostics_retention_days={diagnostics_retention_days()}"
    )
