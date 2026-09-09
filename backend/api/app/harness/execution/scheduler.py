"""单个 tools 节点的持久、有界、保序工具结算。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.errors import AppError, ErrorCode
from app.harness.memory.agent_events import SessionLog, SessionLogWriteError
from app.llm.loop_contracts import Message

from .approval import ApprovalBroker, broker, request_approval
from .loop_tools import (
    ToolExecutionMode,
    ToolExecutionResult,
    execution_mode,
    normalize_tool_output,
    requires_approval,
    tool_argument_error,
)

StreamWriter = Callable[[dict[str, Any]], None]


@dataclass
class _ScheduledCall:
    """完成持久登记与策略准备的单个调用。"""

    call: dict[str, Any]
    call_id: str
    name: str
    call_seq: int
    tool: Any | None
    result: ToolExecutionResult | None = None
    dispatched: bool = False


def _result(
    *,
    log: SessionLog,
    emit: StreamWriter,
    turn: int,
    step: int,
    attempt_id: str,
    call_id: str,
    call_seq: int,
    name: str,
    result: ToolExecutionResult,
) -> Message:
    """先提交工具终态，再发布观察事件。"""
    result = normalize_tool_output(result)
    event = log.append(
        "tool/result",
        {
            "turn": turn,
            "step": step,
            "attempt_id": attempt_id,
            "call_id": call_id,
            "id": call_id,
            "call_seq": call_seq,
            "name": name,
            "content": result.content,
            "output": result.content,
            "status": result.status,
            "is_error": result.is_error,
            "synthetic": result.synthetic or result.status in {"not_started", "outcome_unknown"},
            "display": result.display,
            "metadata": result.metadata,
            **({"error_code": result.error_code} if result.error_code else {}),
            **({"exit_code": result.exit_code} if result.exit_code is not None else {}),
        },
    )
    emit(
        {
            "kind": "tool_result",
            "seq": event["seq"],
            "event_ts": event["ts"],
            "record_type": event["type"],
            "turn": turn,
            "step": step,
            "attempt_id": attempt_id,
            "id": call_id,
            "call_id": call_id,
            "call_seq": call_seq,
            "name": name,
            "output": result.content,
            "status": result.status,
            "error_code": result.error_code,
            "exit_code": result.exit_code,
            "is_error": result.is_error,
        }
    )
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": result.content,
        "is_error": result.is_error,
    }


def _permission_result(exc: AppError) -> ToolExecutionResult:
    """平台拒绝可回填；未知基础设施异常不在此降级。"""
    denied = exc.code in {ErrorCode.UNAUTHORIZED, ErrorCode.WHITELIST, ErrorCode.NEED_APPROVAL, ErrorCode.CONCURRENCY}
    code = str((exc.fields or {}).get("error_code") or exc.code.value)
    return ToolExecutionResult(
        content=f"工具请求未获执行：{exc.code.value}",
        status="denied" if denied else "failed", error_code=code, synthetic=True,
    )


class ToolScheduler:
    """按滚动并发池与独占屏障执行；审批、派发和结果提交均保持模型顺序。"""

    def __init__(self, settings: Any, tools: list[Any], *, approval_broker: ApprovalBroker | None = None):
        """兼容源构造接口，允许与 Runtime 共用注入的审批 broker。"""
        self._approval_broker = approval_broker if approval_broker is not None else broker
        self._settings = settings
        self._by_name = {tool.name: tool for tool in tools}
        self._max_parallel = settings.dsh_max_parallel_tool_calls
        if self._max_parallel < 1 or len(self._by_name) != len(tools):
            raise ValueError("并发数必须为正，工具名不能重复")

    def _mode_for_call(self, call: dict[str, Any]) -> ToolExecutionMode:
        name = call.get("name")
        tool = self._by_name.get(name) if isinstance(name, str) else None
        if tool is not None and self._settings.dsh_require_approval and requires_approval(tool):
            return "exclusive"
        return execution_mode(tool)

    def _record_call(
        self,
        *,
        log: SessionLog,
        turn: int,
        step: int,
        attempt_id: str,
        call: dict[str, Any],
        emit: StreamWriter,
        seen_ids: set[str],
        allow_dispatch: bool,
        dispatch_block_code: str | None,
        dispatch_block_content: str | None = None,
    ) -> _ScheduledCall:
        """先记录调用事实，解决不会进入执行器的参数错误。"""

        call_id = call.get("id")
        name = call.get("name")
        args = call.get("args")
        if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
            raise ValueError("tool scheduler received a call without id or name")

        event = log.append(
            "tool/call",
            {
                "turn": turn,
                "step": step,
                "attempt_id": attempt_id,
                "call_id": call_id,
                "id": call_id,
                "name": name,
                **({"args": args} if isinstance(args, dict) else {}),
                **(
                    {"arguments_raw": call["arguments_raw"]}
                    if isinstance(call.get("arguments_raw"), str)
                    else {}
                ),
                **(
                    {"parse_error": call["parse_error"]}
                    if isinstance(call.get("parse_error"), str)
                    else {}
                ),
            },
        )
        call_seq = event["seq"]
        emit(
            {
                "kind": "tool_call",
                "seq": call_seq,
                "event_ts": event["ts"],
                "record_type": event["type"],
                "turn": turn,
                "step": step,
                "attempt_id": attempt_id,
                "id": call_id,
                "call_id": call_id,
                "call_seq": call_seq,
                "name": name,
                "args": args if isinstance(args, dict) else {},
                "arguments_raw": call.get("arguments_raw"),
                "parse_error": call.get("parse_error"),
            }
        )

        tool = self._by_name.get(name)
        slot = _ScheduledCall(
            call=call,
            call_id=call_id,
            name=name,
            call_seq=call_seq,
            tool=tool,
        )
        if call_id in seen_ids:
            slot.result = ToolExecutionResult(
                content="Error: provider returned a duplicate tool call id.",
                status="failed",
                error_code="duplicate_call_id",
            )
        else:
            seen_ids.add(call_id)

        if slot.result is not None:
            return slot
        if not allow_dispatch:
            slot.result = ToolExecutionResult(
                content=dispatch_block_content
                or "The model response was not eligible to start this tool.",
                status="not_started",
                error_code=dispatch_block_code or "model_response_not_dispatchable",
            )
        elif not isinstance(args, dict) or "parse_error" in call:
            slot.result = ToolExecutionResult(
                content=f"Error: invalid tool arguments: {call.get('parse_error', 'not an object')}",
                status="failed",
                error_code="invalid_arguments",
            )
        elif tool is None:
            slot.result = ToolExecutionResult(
                content=f"Error: unknown tool {name!r}",
                status="failed",
                error_code="unknown_tool",
            )
        elif validation_error := tool_argument_error(tool, args):
            slot.result = ToolExecutionResult(
                content=f"Error: {validation_error}",
                status="failed",
                error_code="invalid_arguments",
            )
        if slot.result is None and tool is not None and hasattr(tool, "bind_call"):
            try:
                slot.tool = tool.bind_call({
                    "session_id": log.session_id, "turn": turn, "step": step,
                    "attempt_id": attempt_id, "call_id": call_id, "call_seq": call_seq,
                })
            except AppError as exc:
                slot.result = _permission_result(exc)
        return slot

    async def _authorize(
        self,
        slot: _ScheduledCall,
        *,
        session_id: str,
        log: SessionLog,
        turn: int,
        step: int,
        attempt_id: str,
        emit: StreamWriter,
    ) -> None:
        """按模型顺序执行权限与审批门禁。"""

        if slot.result is None and slot.tool is not None and hasattr(slot.tool, "check_permission"):
            try:
                slot.tool.check_permission(slot.call["args"])
            except AppError as exc:
                slot.result = _permission_result(exc)
        if (
            slot.result is not None
            or slot.tool is None
            or not self._settings.dsh_require_approval
            or not requires_approval(slot.tool)
        ):
            return

        decision = await request_approval(
            session_id=session_id,
            log=log,
            turn=turn,
            step=step,
            attempt_id=attempt_id,
            call=slot.call,
            emit=emit,
            approval_broker=self._approval_broker,
            scope=getattr(slot.tool, "approval_scope", ""),
            owner_user_id=getattr(getattr(slot.tool, "context", None), "user_id", ""),
            timeout_seconds=getattr(self._settings, "dsh_approval_timeout_seconds", 300),
        )
        if decision in ("allow", "always"):
            return
        error_code, content = {
            "unavailable": (
                "approval_unavailable",
                "Error: tool requires approval but no approval channel is connected",
            ),
            "timeout": ("approval_timeout", "Error: tool approval timed out"),
        }.get(decision, ("approval_denied", "Error: tool call denied by user"))
        slot.result = ToolExecutionResult(
            content=content,
            status="denied",
            error_code=error_code,
        )

    def _dispatch(
        self,
        slot: _ScheduledCall,
        *,
        log: SessionLog,
        turn: int,
        step: int,
        attempt_id: str,
        emit: StreamWriter,
    ) -> asyncio.Task[ToolExecutionResult]:
        """持久提交派发边界后，才允许启动实际执行。"""

        if slot.tool is not None and hasattr(slot.tool, "check_permission"):
            slot.tool.check_permission(slot.call["args"])
        extra = slot.tool.dispatch_data(slot.call["args"]) if hasattr(slot.tool, "dispatch_data") else {}
        # Store 在本次 append 内建 guard；冲突或提交失败均不启动执行器。
        dispatch = log.append(
            "tool/dispatch",
            {
                "turn": turn,
                "step": step,
                "attempt_id": attempt_id,
                "call_id": slot.call_id,
                "id": slot.call_id,
                "call_seq": slot.call_seq,
                "name": slot.name,
                **extra,
            },
        )
        slot.dispatched = True
        emit(
            {
                "kind": "tool_dispatch",
                "seq": dispatch["seq"],
                "event_ts": dispatch["ts"],
                "record_type": dispatch["type"],
                "turn": turn,
                "step": step,
                "attempt_id": attempt_id,
                "id": slot.call_id,
                "call_id": slot.call_id,
                "call_seq": slot.call_seq,
                "name": slot.name,
            }
        )
        return asyncio.create_task(self._invoke(slot))

    @staticmethod
    def _metadata_flag(tool: Any, key: str) -> bool:
        metadata = getattr(tool, "metadata", None) or {}
        return isinstance(metadata, dict) and bool(metadata.get(key))

    @staticmethod
    async def _await_task_to_completion(task: asyncio.Task[Any]) -> Any:
        """重复取消时仍等待自己持有的清理任务完成。"""

        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done():
                    return task.result()
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()

    @classmethod
    async def _invoke_joined_sync_tool(cls, slot: _ScheduledCall) -> object:
        """显式声明的同步工具在线程池执行，取消时等待真实完成。"""

        assert slot.tool is not None
        work = asyncio.create_task(asyncio.to_thread(slot.tool.invoke, slot.call["args"]))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            return await cls._await_task_to_completion(work)

    @classmethod
    async def _invoke(cls, slot: _ScheduledCall) -> ToolExecutionResult:
        """执行一次调用，普通工具错误独立结算。"""

        assert slot.tool is not None
        try:
            if cls._metadata_flag(slot.tool, "dsh_join_on_cancel"):
                output = await cls._invoke_joined_sync_tool(slot)
            else:
                output = await slot.tool.ainvoke(slot.call["args"])
        except asyncio.CancelledError:
            if cls._metadata_flag(slot.tool, "dsh_cancellable"):
                return ToolExecutionResult(
                    content="Error: tool execution cancelled",
                    status="cancelled",
                    error_code="tool_cancelled",
                )
            raise
        except SessionLogWriteError:
            # 持久边界故障不能被当作普通工具失败后继续派发。
            raise
        except AppError as exc:
            return _permission_result(exc)
        except Exception:
            return ToolExecutionResult(
                content="工具执行失败（INTERNAL）",
                status="failed",
                error_code="tool_exception",
            )
        return normalize_tool_output(output)

    @staticmethod
    def _unknown_after_dispatch() -> ToolExecutionResult:
        return ToolExecutionResult(
            content=(
                "The tool was interrupted after dispatching. Its external outcome is unknown; "
                "inspect before retrying."
            ),
            status="outcome_unknown",
            error_code="tool_outcome_unknown",
        )

    @staticmethod
    def _cancelled_before_dispatch() -> ToolExecutionResult:
        return ToolExecutionResult(
            content="Error: tool call cancelled before dispatch",
            status="not_started",
            error_code="tool_cancelled_before_dispatch",
        )

    @staticmethod
    def _commit_ready(
        slots: list[_ScheduledCall],
        committed: int,
        *,
        log: SessionLog,
        emit: StreamWriter,
        turn: int,
        step: int,
        attempt_id: str,
        messages: list[Message],
    ) -> int:
        """只提交已连续完成的模型顺序前缀。"""

        while committed < len(slots):
            slot = slots[committed]
            if slot.result is None:
                break
            messages.append(
                _result(
                    log=log,
                    emit=emit,
                    turn=turn,
                    step=step,
                    attempt_id=attempt_id,
                    call_id=slot.call_id,
                    call_seq=slot.call_seq,
                    name=slot.name,
                    result=slot.result,
                )
            )
            committed += 1
        return committed

    async def _drain_started(
        self,
        in_flight: dict[asyncio.Task[ToolExecutionResult], _ScheduledCall],
        *,
        preserve_known_results: bool,
    ) -> None:
        """停止已启动工具，等待全部到达可确认边界。"""

        tasks = list(in_flight)
        for task in tasks:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for task, outcome in zip(tasks, outcomes, strict=True):
            slot = in_flight[task]
            if preserve_known_results:
                if isinstance(outcome, ToolExecutionResult):
                    slot.result = outcome
                else:
                    slot.result = self._unknown_after_dispatch()
        in_flight.clear()

    def _settle_cancelled_remainder(
        self,
        *,
        calls: list[dict[str, Any]],
        next_to_start: int,
        slots: list[_ScheduledCall],
        log: SessionLog,
        turn: int,
        step: int,
        attempt_id: str,
        emit: StreamWriter,
        seen_ids: set[str],
    ) -> None:
        """为取消时尚未启动的调用补齐有序终态。"""

        for slot in slots:
            if slot.result is None and not slot.dispatched:
                slot.result = self._cancelled_before_dispatch()

        for call in calls[next_to_start:]:
            slot = self._record_call(
                log=log,
                turn=turn,
                step=step,
                attempt_id=attempt_id,
                call=call,
                emit=emit,
                seen_ids=seen_ids,
                allow_dispatch=False,
                dispatch_block_code="tool_cancelled_before_dispatch",
                dispatch_block_content="Error: tool call cancelled before dispatch",
            )
            slots.append(slot)

    async def _run_group(
        self,
        *,
        session_id: str,
        log: SessionLog,
        turn: int,
        step: int,
        attempt_id: str,
        calls: list[dict[str, Any]],
        mode: ToolExecutionMode,
        emit: StreamWriter,
        allow_dispatch: bool,
        dispatch_block_code: str | None,
        messages: list[Message],
        seen_ids: set[str],
    ) -> int:
        """执行单个独占调用，或补充滚动并发池。"""

        slots: list[_ScheduledCall] = []
        in_flight: dict[asyncio.Task[ToolExecutionResult], _ScheduledCall] = {}
        next_to_start = 0
        committed = 0
        pool_limit = self._max_parallel if mode == "parallel" else 1

        def can_start_next() -> bool:
            if next_to_start >= len(calls) or len(in_flight) >= pool_limit:
                return False
            if next_to_start == 0:
                return True
            return mode == "parallel" and self._mode_for_call(calls[next_to_start]) == "parallel"

        async def fill_pool() -> None:
            nonlocal next_to_start, committed
            while can_start_next():
                call = calls[next_to_start]
                slot = self._record_call(
                    log=log,
                    turn=turn,
                    step=step,
                    attempt_id=attempt_id,
                    call=call,
                    emit=emit,
                    seen_ids=seen_ids,
                    allow_dispatch=allow_dispatch,
                    dispatch_block_code=dispatch_block_code,
                )
                slots.append(slot)
                next_to_start += 1
                await self._authorize(
                    slot,
                    session_id=session_id,
                    log=log,
                    turn=turn,
                    step=step,
                    attempt_id=attempt_id,
                    emit=emit,
                )
                if slot.result is None:
                    try:
                        task = self._dispatch(
                            slot,
                            log=log,
                            turn=turn,
                            step=step,
                            attempt_id=attempt_id,
                            emit=emit,
                        )
                        in_flight[task] = slot
                    except AppError as exc:
                        slot.result = _permission_result(exc)
                committed = self._commit_ready(
                    slots,
                    committed,
                    log=log,
                    emit=emit,
                    turn=turn,
                    step=step,
                    attempt_id=attempt_id,
                    messages=messages,
                )

        try:
            await fill_pool()
            while in_flight:
                done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    slot = in_flight.pop(task)
                    try:
                        slot.result = task.result()
                    except asyncio.CancelledError:
                        slot.result = self._unknown_after_dispatch()
                committed = self._commit_ready(
                    slots,
                    committed,
                    log=log,
                    emit=emit,
                    turn=turn,
                    step=step,
                    attempt_id=attempt_id,
                    messages=messages,
                )
                await fill_pool()

            if committed != len(slots):
                raise RuntimeError("tool scheduler reached an unresolved result")
            return next_to_start
        except asyncio.CancelledError:
            drain = asyncio.create_task(
                self._drain_started(in_flight, preserve_known_results=True)
            )
            await self._await_task_to_completion(drain)
            self._settle_cancelled_remainder(
                calls=calls,
                next_to_start=next_to_start,
                slots=slots,
                log=log,
                turn=turn,
                step=step,
                attempt_id=attempt_id,
                emit=emit,
                seen_ids=seen_ids,
            )
            self._commit_ready(
                slots,
                committed,
                log=log,
                emit=emit,
                turn=turn,
                step=step,
                attempt_id=attempt_id,
                messages=messages,
            )
            raise
        except Exception:
            drain = asyncio.create_task(self._drain_started(in_flight, preserve_known_results=False))
            await self._await_task_to_completion(drain)
            raise

    async def execute(
        self,
        *,
        session_id: str,
        log: SessionLog,
        turn: int,
        step: int,
        attempt_id: str,
        calls: list[dict[str, Any]],
        emit: StreamWriter,
        allow_dispatch: bool,
        dispatch_block_code: str | None = None,
    ) -> list[Message]:
        """结算模型全部调用，保持原始顺序和有界并发。"""

        messages: list[Message] = []
        seen_ids: set[str] = set()
        next_to_run = 0
        while next_to_run < len(calls):
            consumed = await self._run_group(
                session_id=session_id,
                log=log,
                turn=turn,
                step=step,
                attempt_id=attempt_id,
                calls=calls[next_to_run:],
                mode=self._mode_for_call(calls[next_to_run]),
                emit=emit,
                allow_dispatch=allow_dispatch,
                dispatch_block_code=dispatch_block_code,
                messages=messages,
                seen_ids=seen_ids,
            )
            if consumed <= 0:
                raise RuntimeError("tool scheduler made no progress")
            next_to_run += consumed
        return messages


    async def run(self, **kwargs: Any) -> list[Message]:
        """保留迁入方使用 run 的别名；实际源接口 execute 同时可用。"""
        return await self.execute(**kwargs)
