"""会话独占运行时，负责七节点图任务、订阅、取消与确定性恢复。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from app.agent.loop import GraphRunContext, TurnDependencies
from app.harness.contracts.fact_log import RuntimeLog, execution_key, log_run_id
from app.harness.execution.approval import ApprovalGate, broker
from app.harness.memory.agent_messages import derive_messages
from app.harness.memory.agent_recovery import RecoveryEvent, recovery_events
from app.llm.loop_contracts import ReasoningEffort, header_fingerprint

if TYPE_CHECKING:
    from app.agent.collaboration_scope import TurnChildren

RuntimeSubscriber = Callable[[dict[str, Any]], None]


class TurnAlreadyRunningError(RuntimeError):
    """会话已有活动回合。"""


class RuntimeClosedError(RuntimeError):
    """运行时已关闭，不能接受新输入。"""


class AgentRuntime:
    """持有单会话的活动回合、观察者及确定性结算。"""

    def __init__(
        self, log: RuntimeLog, graph: Any, *, approval_broker: Any = None,
        writer_id: str | None = None, actor_id: str | None = None,
    ):
        """绑定已授权的日志及固定模型图；writer 租约由主 service 管理。"""
        self.writer_id = writer_id
        self.actor_id = actor_id
        self._broker = approval_broker if approval_broker is not None else broker
        self.log = log
        self._execution_key = execution_key(log)
        self._children: TurnChildren | None = None
        self._graph = graph
        self._lock = asyncio.Lock()
        self._subscribers: set[RuntimeSubscriber] = set()
        self._task: asyncio.Task[None] | None = None
        self._active_turn: int | None = None
        self._cancelling = False
        self._closed = False
        self._approval_gate: ApprovalGate | None = None
        self._started_turn_here = False

    @property
    def session_id(self) -> str:
        """返回此运行时绑定的持久会话标识。"""
        return self.log.session_id

    @property
    def running(self) -> bool:
        """判断当前是否仍持有活动图任务。"""
        return self._task is not None and not self._task.done()

    @property
    def execution_id(self) -> str:
        """返回图和审批的运行域；工具授权仍使用真实 session_id。"""
        return self._execution_key

    @property
    def active_turn(self) -> int | None:
        """仅活动期间暴露当前回合编号。"""
        return self._active_turn if self.running else None

    def subscribe(self, subscriber: RuntimeSubscriber) -> Callable[[], None]:
        """订阅已提交事件，不依赖具体 WebSocket。"""
        self._subscribers.add(subscriber)

        def unsubscribe() -> None:
            """移除当前观察者，不取消控制者的活动回合。"""
            self._subscribers.discard(subscriber)

        return unsubscribe

    def set_approval_gate(self, gate: ApprovalGate | None, *, replace: bool = False) -> bool:
        """绑定审批路由，默认拒绝抢占活动控制连接。"""
        previous = self._approval_gate
        if previous == gate:
            return True
        if previous is not None and self.running and not replace:
            return False
        self._approval_gate = gate
        if previous is not None:
            self._broker.unregister(self.execution_id, previous)
        if gate is not None:
            self._broker.register(self.execution_id, gate)
        return True

    def clear_approval_gate(self, gate: ApprovalGate) -> bool:
        """仅允许当前审批路由所有者解除绑定。"""
        if self._approval_gate != gate:
            return False
        self.set_approval_gate(None, replace=True)
        return True

    def owns_approval_gate(self, gate: ApprovalGate) -> bool:
        """判断审批路由是否仍拥有控制权。"""
        return self._approval_gate == gate

    def _publish(self, payload: dict[str, Any]) -> None:
        """提交后通知订阅者；坏订阅者不影响回合执行。"""
        # Graph 节点只携带业务字段；Runtime 在这里补上 Session 身份，使同一事件
        # 可以被 WebSocket、测试或其他订阅者使用，而无需了解图的运行上下文。
        payload = {"session_id": self.session_id, **payload}
        if (run_id := log_run_id(self.log)) is not None:
            payload = {**payload, "run_id": run_id}
        for subscriber in tuple(self._subscribers):
            try:
                subscriber(payload)
            except Exception:
                self._subscribers.discard(subscriber)

    def _next_turn(self) -> int:
        """从已提交回合事实推导候选序号，最终以持久端口分配为准。"""
        turns = [
            event["data"].get("turn", 0)
            for event in self.log.read()
            if event.get("type") == "turn/start" and isinstance(event.get("data"), dict)
        ]
        return max((turn for turn in turns if isinstance(turn, int)), default=0) + 1

    def _request_header_state(self) -> tuple[str | None, int | None]:
        """为新回合恢复最近一次持久请求头。"""
        for event in reversed(self.log.read()):
            if event.get("type") != "request/header":
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            header = data.get("header")
            if not isinstance(header, dict):
                continue
            fingerprint = data.get("fingerprint")
            if not isinstance(fingerprint, str):
                fingerprint = header_fingerprint(header)
            seq = event.get("seq")
            if isinstance(seq, int):
                return fingerprint, seq
        return None, None

    async def recover(self) -> list[dict[str, Any]]:
        """显式结算此前中断回合；持久日志调用者必须已确认自身 writer 租约。"""
        async with self._lock:
            if self._closed:
                raise RuntimeClosedError(self.session_id)
            if self._task is not None and self._task.cancelled():
                # 首次调度前取消的图已经 done，但子任务可能仍在运行；先复用同一
                # 取消结算入口，避免提前发布 interrupted 或覆盖真实 cancelled 原因。
                return await self._settle_cancelled_task_locked(self._task)
            if self.running:
                return []
            return self._append_recovery("interrupted")

    async def start_turn(
        self,
        content: str | list[dict[str, Any]],
        *,
        reasoning_effort: ReasoningEffort | None = None,
        dependencies: TurnDependencies | None = None,
        client_message_id: str | None = None,
        command_context: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> int:
        """持久接收一条输入，并启动唯一后台图任务。"""
        async with self._lock:
            if self._closed:
                raise RuntimeClosedError(self.session_id)
            if self._task is not None and self._task.done():
                # 首次调度前被取消的任务不会进入 _drive，需在持锁状态补齐结算。
                await self._settle_cancelled_task_locked(self._task)
            if self.running:
                raise TurnAlreadyRunningError(self.session_id)
            # 新 Turn 前先结算此前未闭合的 Turn；当前实现的 recover 是收尾，不是
            # 从 LangGraph checkpoint 的中间节点继续执行。
            begin_turn = getattr(self.log, "begin_turn", None)
            if callable(begin_turn):
                # 不替别的进程接管开放回合；主 service 先持租约显式 recover。
                if recovery_events(self.log.read()):
                    raise RuntimeError("persistent runtime requires explicit owned recovery")
            else:
                self._append_recovery("interrupted")
            if actor_id is not None or self.actor_id is not None:
                self.log.actor_id = actor_id if actor_id is not None else self.actor_id
            if command_context is not None:
                self.log.command_context = deepcopy(command_context)
            turn = self._next_turn()
            request_fingerprint, request_header_seq = self._request_header_state()
            header_reason = (
                "resume"
                if not self._started_turn_here and request_header_seq is not None
                else dependencies.history_transition_reason if dependencies is not None else None
            )
            # 先持久接收用户输入，再启动后台图任务。这样图任务创建失败时，输入仍能
            # 从会话日志定位和诊断，浏览器也不会先看到一个不存在的 Turn。
            user_message = {"turn": turn, "content": content, "source": "user"}
            if reasoning_effort is not None:
                user_message["reasoning_effort"] = reasoning_effort
            if client_message_id is not None:
                user_message["client_message_id"] = client_message_id
            if callable(begin_turn):
                started, user_event = begin_turn(user_message, writer_id=self.writer_id)
                turn = started["data"]["turn"]
                # begin_turn 可返回幂等收据；已结算的旧输入不重新请求模型。
                if any(
                    event["type"] == "turn/end" and event["data"].get("turn") == turn
                    for event in self.log.read()
                ):
                    return turn
            else:
                started = self.log.append("turn/start", {"turn": turn})
                user_event = self.log.append("user/message", user_message)
            # 根据已提交历史建立本次初始上下文；图内之后会把 assistant/tool 消息继续
            # 追加到 AgentState.messages，直到本 Turn 结束。
            messages = derive_messages(
                self.log.read(),
                protocol_state_compatibility=(
                    dependencies.protocol_state_compatibility
                    if dependencies is not None else None
                ),
            )
            self._publish({
                "kind": "user_message", "seq": user_event["seq"],
                "event_ts": user_event["ts"], "record_type": user_event["type"],
                **deepcopy(user_event["data"]),
            })
            self._publish(
                {
                    "kind": "turn_start",
                    "seq": started["seq"],
                    "event_ts": started["ts"],
                    "record_type": started["type"],
                    "turn": turn,
                }
            )
            self._children = dependencies.children if dependencies is not None else None
            task = asyncio.create_task(
                self._drive(
                    turn,
                    messages,
                    request_fingerprint,
                    request_header_seq,
                    header_reason,
                    reasoning_effort,
                    dependencies,
                ),
                name=f"agent-turn-{self.execution_id}",
            )
            self._task = task
            self._active_turn = turn
            self._cancelling = False
            self._started_turn_here = True
            task.add_done_callback(self._schedule_cancelled_settlement)
            return turn

    async def submit(self, content: str | list[dict[str, Any]], **kwargs: Any) -> int:
        """命令层入口，保留 start_turn 的全部兼容参数与互斥语义。"""
        return await self.start_turn(content, **kwargs)

    async def replace_graph(self, graph: Any) -> None:
        """仅在空闲边界更换已编译的模型或协议档，活动回合不静默切换。"""
        async with self._lock:
            if self._closed:
                raise RuntimeClosedError(self.session_id)
            if self.running:
                raise TurnAlreadyRunningError(self.session_id)
            self._graph = graph

    async def cancel(self) -> bool:
        """请求取消，由恢复逻辑异步结算图边界。"""
        async with self._lock:
            if not self.running:
                return False
            assert self._task is not None
            if self._cancelling:
                return True
            # 命令 service 可能已将取消与回执原子提交，断连取消才需本地补写。
            if not any(
                event["type"] == "runtime/cancel_requested"
                and event["data"].get("turn") == self._active_turn
                for event in self.log.read()
            ):
                event = self.log.append(
                    "runtime/cancel_requested", {"turn": self._active_turn}
                )
                self._publish({
                    "kind": "cancel_requested", "seq": event["seq"],
                    "event_ts": event["ts"], "record_type": event["type"],
                    "turn": self._active_turn,
                })
            self._cancelling = True
            self._task.cancel()
            return True

    async def wait(self) -> None:
        """等待当前回合完成及取消结算。"""
        task = self._task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        await self._settle_cancelled_task(task)

    async def close(self) -> None:
        """禁止新输入并恰好一次地结算活动任务。"""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            task = self._task
            if task is not None and not task.done() and not self._cancelling:
                self._cancelling = True
                task.cancel()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            await self._settle_cancelled_task(task)
        self.set_approval_gate(None)
        self._broker.clear_session(self.execution_id)
        self._subscribers.clear()

    def _schedule_cancelled_settlement(self, task: asyncio.Task[None]) -> None:
        """结算在驱动协程首次执行前就被取消的任务。"""

        if task.cancelled():
            asyncio.create_task(
                self._settle_cancelled_task(task),
                name=f"agent-cancel-settlement-{self.session_id}",
            )

    async def _settle_cancelled_task(self, task: asyncio.Task[None]) -> None:
        """持锁补齐首次调度前取消的任务边界。"""
        async with self._lock:
            await self._settle_cancelled_task_locked(task)

    async def _settle_cancelled_task_locked(self, task: asyncio.Task[None]) -> list[dict[str, Any]]:
        """在持锁状态结算尚未启动的取消任务，并返回本次提交的事实。"""

        if self._task is not task or not task.cancelled():
            return []
        if self._children is not None:
            await self._children.close(propagate_cancel=False)
        committed = self._append_recovery("cancelled")
        self._task = None
        self._active_turn = None
        self._cancelling = False
        return committed

    async def _drive(
        self,
        turn: int,
        messages: list[dict[str, Any]],
        request_fingerprint: str | None,
        request_header_seq: int | None,
        request_header_reason: str | None,
        reasoning_effort: ReasoningEffort | None,
        dependencies: TurnDependencies | None,
    ) -> None:
        # GraphRunContext 是进程内依赖（日志对象等），故意不写入 Checkpoint；initial
        # 则只包含可序列化的 AgentState，作为本次 Turn 的 ReAct 起点。
        """驱动七节点图，并在取消或异常后补齐持久边界。"""
        context = GraphRunContext(
            session_id=self.session_id, turn=turn, log=self.log, dependencies=dependencies
        )
        config = {
            "recursion_limit": getattr(self._graph, "loop_recursion_limit", 25),
            "configurable": {
                "thread_id": self.execution_id,
                "checkpoint_ns": "agent-loop-v2",
                "run_context": context,
                "reasoning_effort": reasoning_effort,
            }
        }
        initial = {
            "session_id": self.session_id,
            "turn": turn,
            "step": 0,
            "steps_used": 0,
            "model_attempts": 0,
            "phase": "running",
            "messages": messages,
            "request_fingerprint": request_fingerprint,
            "request_header_seq": request_header_seq,
            "request_header_reason": request_header_reason,
            "pending_calls": [],
            "model_finish": "",
            "model_error": "",
            "model_error_code": "",
            "retryable_error": False,
            "step_open": False,
            "continue_loop": False,
            "stop_reason": "",
        }
        # custom stream 是 graph.py 显式发出的业务事件，并非 Provider SDK 原始 chunk。
        # last_published_seq 用于取消/异常时补发 Scheduler 已落盘但尚未转发的工具事实。
        last_published_seq = 0
        try:
            async for payload in self._graph.astream(initial, config, stream_mode="custom"):
                # Runtime 只转发，不改变图路由或业务状态；Handler 再投影为 WebSocket 帧。
                self._publish(payload)
                seq = payload.get("seq")
                if isinstance(seq, int):
                    last_published_seq = max(last_published_seq, seq)
        except asyncio.CancelledError:
            if self._children is not None:
                await self._children.close(propagate_cancel=False)
            # 图流中断前可能已写入助手消息或工具事实。先补发这些记录，再统一追加
            # 取消收尾，避免 UI 已经收到取消却漏掉 assistant_end 或 tool_result。
            self._publish_unpublished_events(turn=turn, after_seq=last_published_seq)
            self._append_recovery("cancelled")
            raise
        except Exception:
            if self._children is not None:
                await self._children.close(propagate_cancel=False)
            # 图异常不能让 Session 停在无终态状态：记录 runtime/error，并将确定的
            # 已落盘事件补发给订阅者后再交由 recovery 写收尾记录。
            failed = self.log.append(
                "runtime/error",
                {"turn": turn, "error": "Agent 循环执行失败", "error_code": "graph_exception"},
            )
            self._publish(
                {
                    "kind": "runtime_error",
                    "seq": failed["seq"],
                    "event_ts": failed["ts"],
                    "record_type": failed["type"],
                    "turn": turn,
                    "error": "Agent 循环执行失败",
                    "error_code": "graph_exception",
                }
            )
            self._publish_unpublished_events(turn=turn, after_seq=last_published_seq)
            self._append_recovery("error")
        finally:
            async with self._lock:
                if self._task is asyncio.current_task():
                    self._task = None
                    self._active_turn = None
                    self._cancelling = False

    def _publish_unpublished_events(self, *, turn: int, after_seq: int) -> None:
        """补发图流中断时未转发的助手和调度事实。"""

        for event in self.log.read():
            seq = event.get("seq")
            data = event.get("data")
            if not isinstance(seq, int) or seq <= after_seq or not isinstance(data, dict):
                continue
            if data.get("turn") != turn:
                continue

            if event.get("type") == "assistant/message":
                message = data.get("message")
                content = data.get("content")
                if not isinstance(content, str) and isinstance(message, dict):
                    content = message.get("content")
                if not isinstance(content, str):
                    content = ""
                reasoning_content = data.get("reasoning_content")
                if not isinstance(reasoning_content, str) and isinstance(message, dict):
                    reasoning_content = message.get("reasoning_content")
                if not isinstance(reasoning_content, str):
                    reasoning_content = ""
                tool_calls = data.get("tool_calls")
                if not isinstance(tool_calls, list) and isinstance(message, dict):
                    tool_calls = message.get("tool_calls")
                if not isinstance(tool_calls, list):
                    tool_calls = []
                usage = data.get("usage")
                if not isinstance(usage, dict):
                    usage = {}
                source = message.get("source") if isinstance(message, dict) else None
                interrupted = bool(data.get("interrupted", False))
                common = {
                    "seq": seq,
                    "event_ts": event.get("ts"),
                    "record_type": event.get("type"),
                    "turn": turn,
                    "step": data.get("step", 0),
                    "attempt_id": data.get("attempt_id", "recovery"),
                }
                self._publish(
                    {
                        "kind": "assistant_message",
                        **common,
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "tool_calls": tool_calls,
                        "usage": usage,
                        "finish_reason": data.get("finish_reason"),
                        "source": source,
                        "interrupted": interrupted,
                    }
                )
                self._publish(
                    {
                        "kind": "assistant_end",
                        **common,
                        "outcome": "committed",
                        "committed_seq": seq,
                        "interrupted": interrupted,
                    }
                )
                continue

            if event.get("type") == "tool/call":
                call_id = data.get("call_id", data.get("id"))
                name = data.get("name")
                if isinstance(call_id, str) and isinstance(name, str):
                    self._publish(
                        {
                            "kind": "tool_call",
                            "seq": seq,
                            "event_ts": event.get("ts"),
                            "record_type": event.get("type"),
                            "turn": turn,
                            "step": data.get("step", 0),
                            "attempt_id": data.get("attempt_id", "recovery"),
                            "id": call_id,
                            "call_id": call_id,
                            "call_seq": seq,
                            "name": name,
                            "args": data.get("args", {}),
                            "arguments_raw": data.get("arguments_raw"),
                            "parse_error": data.get("parse_error"),
                        }
                    )
                continue

            if event.get("type") != "tool/result":
                continue
            call_id = data.get("call_id", data.get("id"))
            name = data.get("name")
            call_seq = data.get("call_seq")
            if isinstance(call_id, str) and isinstance(name, str) and isinstance(call_seq, int):
                self._publish(
                    {
                        "kind": "tool_result",
                        "seq": seq,
                        "event_ts": event.get("ts"),
                        "record_type": event.get("type"),
                        "turn": turn,
                        "step": data.get("step", 0),
                        "attempt_id": data.get("attempt_id", "recovery"),
                        "id": call_id,
                        "call_id": call_id,
                        "call_seq": call_seq,
                        "name": name,
                        "output": data.get("content", data.get("output", "")),
                        "status": data.get("status"),
                        "error_code": data.get("error_code"),
                        "exit_code": data.get("exit_code"),
                        "synthetic": data.get("synthetic", False),
                        "is_error": data.get("is_error", True),
                    }
                )

    def _append_recovery(self, reason: str) -> list[dict[str, Any]]:
        """按顺序持久化并发布确定性恢复记录。"""
        committed: list[dict[str, Any]] = []
        for repair in recovery_events(self.log.read(), turn_reason=reason):
            event = self.log.append(repair.type, repair.data)
            committed.append(event)
            self._publish(self._recovery_payload(repair, event))
        return committed

    @staticmethod
    def _recovery_payload(repair: RecoveryEvent, event: dict[str, Any]) -> dict[str, Any]:
        """按事实类型发布恢复事件，不将已入队的成功结果误标为失败。"""
        data = repair.data
        if repair.type in {
            "approval/decided", "question/answered", "task_confirmation/resolved",
        }:
            return {
                "kind": repair.type.replace("/", "_"),
                "seq": event["seq"], "event_ts": event["ts"], "record_type": event["type"],
                **deepcopy(data),
            }
        if repair.type == "tool/result":
            return {
                "kind": "tool_result",
                "seq": event["seq"],
                "event_ts": event["ts"],
                "record_type": event["type"],
                "turn": data.get("turn", 0),
                "step": data.get("step", 0),
                "attempt_id": data.get("attempt_id", "recovery"),
                "id": data["id"],
                "call_id": data["call_id"],
                "call_seq": data.get("call_seq"),
                "name": data["name"],
                "output": data["content"],
                "status": data["status"],
                "error_code": data.get("error_code"),
                "exit_code": data.get("exit_code"),
                "synthetic": data.get("synthetic", False),
                "is_error": data["status"] != "succeeded",
                **({"task_id": data["task_id"]} if "task_id" in data else {}),
            }
        if repair.type == "step/end":
            return {
                "kind": "step_end",
                "seq": event["seq"],
                "event_ts": event["ts"],
                "record_type": event["type"],
                "turn": data["turn"],
                "step": data["step"],
                "reason": data.get("reason"),
            }
        if repair.type == "turn/end":
            return {
                "kind": "turn_end",
                "seq": event["seq"],
                "event_ts": event["ts"],
                "record_type": event["type"],
                "turn": data["turn"],
                "reason": data["reason"],
            }
        return {
            "kind": "recovery",
            "seq": event["seq"],
            "event_ts": event["ts"],
            "record_type": event["type"],
            "type": repair.type,
        }


class RuntimeRegistry:
    """按授权会话与可选 run_id 缓存，专家不能命中主运行或其他专家。"""

    def __init__(self, graph: Any):
        """初始化当前对象的独立状态。"""
        self._graph = graph
        self._runtimes: dict[tuple[str, str | None], AgentRuntime] = {}
        self._lock = asyncio.Lock()

    async def get(self, log: RuntimeLog) -> AgentRuntime:
        """按独立事实域取得运行时，不改变持久写者归属。"""
        async with self._lock:
            key = (log.session_id, log_run_id(log))
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = AgentRuntime(log, self._graph)
                self._runtimes[key] = runtime
            return runtime

    async def close(self) -> None:
        """关闭缓存内运行时并等待取消结算；日志生命周期归调用方。"""
        async with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        await asyncio.gather(*(runtime.close() for runtime in runtimes), return_exceptions=True)
