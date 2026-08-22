"""批次工具并行门面：默认策略由调用方决定，结果始终按输入顺序收敛。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.errors import ErrorClass
from app.harness.contracts.tool_call import ExecutionOutcome, ToolCall, ToolCallBatch
from app.harness.contracts.trace import TraceContext


class ToolMetadata(Protocol):
    """并行门禁所需的最小注册表视图，避免编排层依赖具体执行实现。"""

    parallel_safe: bool
    permission: str


@dataclass(frozen=True)
class ParallelDecision:
    """一批工具的门禁结论；开关关闭时只能退回串行。"""

    execute_in_parallel: bool
    violation_reason: str | None = None


@dataclass(frozen=True)
class PreparedBatchCall:
    """已经绑定执行子 span 的调用，供 gather 按原始顺序收敛。"""

    call: ToolCall
    trace: TraceContext


def _has_data_dependency(arguments: dict) -> bool:
    """拒绝显式依赖前项结果的调用，避免错误地并发执行有因果关系的动作。"""
    dependency_keys = {"depends_on", "depends_on_call_id", "previous_call_id"}
    if any(key in arguments for key in dependency_keys):
        return True
    return any(isinstance(value, str) and "${call-" in value for value in arguments.values())


def decide_parallel(
    batch: ToolCallBatch,
    *,
    enabled: bool,
    max_calls: int,
    lookup: Callable[[str], ToolMetadata | None],
) -> ParallelDecision:
    """执行冻结的三分支策略：关则串行，开且全安全才并行，否则整批拒绝。"""
    if not enabled:
        return ParallelDecision(execute_in_parallel=False)
    if len(batch.tool_calls) > max_calls:
        return ParallelDecision(False, f"批次超过并行上限 {max_calls}")
    for call in batch.tool_calls:
        definition = lookup(call.tool or "")
        if definition is None:
            return ParallelDecision(False, "批次含未注册工具")
        if not definition.parallel_safe or definition.permission != "read":
            return ParallelDecision(False, "批次含非只读或未授权并行工具")
        if _has_data_dependency(call.arguments):
            return ParallelDecision(False, "批次调用存在数据依赖")
    return ParallelDecision(execute_in_parallel=True)


async def execute_parallel(
    calls: list[PreparedBatchCall],
    *,
    cancel: CancellationToken,
    run_call: Callable[[PreparedBatchCall], Awaitable[ExecutionOutcome]],
    max_calls: int,
) -> list[ExecutionOutcome]:
    """并发执行并按输入顺序返回 Outcome；单项失败不取消其余项。"""
    semaphore = asyncio.Semaphore(max(1, max_calls))

    async def _run(prepared: PreparedBatchCall) -> ExecutionOutcome:
        if cancel.is_cancelled():
            return ExecutionOutcome.cancelled(
                prepared.call,
                trace_id=prepared.trace.trace_id,
                span_id=prepared.trace.span_id,
                parent_span_id=prepared.trace.parent_span_id,
            )
        async with semaphore:
            if cancel.is_cancelled():
                return ExecutionOutcome.cancelled(
                    prepared.call,
                    trace_id=prepared.trace.trace_id,
                    span_id=prepared.trace.span_id,
                    parent_span_id=prepared.trace.parent_span_id,
                )
            return await run_call(prepared)

    try:
        gathered = await asyncio.gather(*(_run(call) for call in calls), return_exceptions=True)
    except asyncio.CancelledError:
        # 当前协程被 /stop 取消时，不再启动后续工作；线程中的远端动作仅能标记请求取消。
        return [
            ExecutionOutcome.cancelled(
                prepared.call,
                trace_id=prepared.trace.trace_id,
                span_id=prepared.trace.span_id,
                parent_span_id=prepared.trace.parent_span_id,
                requested=True,
            )
            for prepared in calls
        ]

    outcomes: list[ExecutionOutcome] = []
    for prepared, item in zip(calls, gathered, strict=True):
        if isinstance(item, ExecutionOutcome):
            outcomes.append(item)
            continue
        if isinstance(item, TurnCancelled | asyncio.CancelledError) or cancel.is_cancelled():
            outcomes.append(
                ExecutionOutcome.cancelled(
                    prepared.call,
                    trace_id=prepared.trace.trace_id,
                    span_id=prepared.trace.span_id,
                    parent_span_id=prepared.trace.parent_span_id,
                    requested=isinstance(item, asyncio.CancelledError),
                )
            )
            continue
        # run_call 正常会自行归一异常；此处只兜住测试桩或未来适配器的遗漏。
        outcomes.append(
            ExecutionOutcome.failed(
                prepared.call,
                ErrorClass.TOOL_INTERNAL_ERROR,
                "操作失败",
                trace_id=prepared.trace.trace_id,
                span_id=prepared.trace.span_id,
                parent_span_id=prepared.trace.parent_span_id,
            )
        )
    return outcomes
