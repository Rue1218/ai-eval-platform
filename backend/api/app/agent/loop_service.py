"""平台身份、事务与源循环的接线；WS 只调用快速命令，不等待模型整轮。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.execution.approval import ApprovalBroker
from app.harness.memory.agent_events import SessionLog
from app.models import Session, User
from app.routers.ws_v2 import CommandReceipt, StreamSnapshot, WsAccess
from app.session_access import require_visible_session

from .events import frame, scrub
from .loop import TurnDependencies, build_agent
from .loop_settings import LoopSettings
from .runtime import AgentRuntime

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    """一个进程拥有的会话运行时，控制连接与浏览订阅互不混用。"""

    log: SessionLog
    runtime: AgentRuntime
    controller: tuple[str, str] | None = None
    interactions: dict[str, asyncio.Future] = field(default_factory=dict)
    cleanup: asyncio.Task | None = None
    approval_gate: Callable | None = None
    approval_owner: tuple[str, str] | None = None
    writer_released: bool = False


class LoopService:
    """唯一平台装配点；测试可注入真实循环所用的可控模型，其他边界照常执行。"""

    def __init__(self, session_factory=None, *, dependency_builder=None):
        if session_factory is None:
            from app.db import SessionLocal

            session_factory = SessionLocal
        self.session_factory = session_factory
        self.dependency_builder = dependency_builder
        self.entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._observers: dict[str, dict[str, tuple[str, Callable]]] = {}
        self._broker = ApprovalBroker()
        self._closed = False

    async def authenticate(self, ticket: str) -> str:
        """复用一次性短票与账号状态检查，不另造认证机制。"""
        from app.routers.ws import _consume_ws_ticket

        with self.session_factory() as db:
            return str(_consume_ws_ticket(db, ticket).id)

    async def authorize(self, actor_id: str, session_id: str) -> WsAccess:
        """每次操作及发送前复验账号和会话 ACL，管理员诊断不授予他人确认权。"""
        with self.session_factory() as db:
            user = db.get(User, actor_id)
            if user is None or user.disabled:
                raise AppError(ErrorCode.UNAUTHORIZED, "成员不可用")
            session = require_visible_session(db, session_id, actor_id)
            if session.engine_version != "agent_loop_v2":
                raise AppError(ErrorCode.VALIDATION, "请使用该会话对应的旧协议入口")
            owner = session.user_id == actor_id
            interactive = session.pending_confirm_author_id in (None, actor_id)
            return WsAccess(write=True, trace=owner or user.role == "admin", reasoning=owner,
                            interactions=interactive)

    async def attach(self, actor_id: str, session_id: str, connection_id: str, on_transient: Callable) -> None:
        """先登记瞬态订阅，不创建模型客户端、不抢占会话写者。"""
        await self.authorize(actor_id, session_id)
        self._observers.setdefault(session_id, {})[connection_id] = (actor_id, on_transient)

    async def snapshot(self, actor_id: str, session_id: str) -> StreamSnapshot:
        """快照与 H 取自同一事务，交互卡按实际回执成员裁剪。"""
        access = await self.authorize(actor_id, session_id)
        log = SessionLog(session_id, self.session_factory)
        log.bridge_worker()
        cursor, state = log.snapshot()
        if state.get("pending_confirm"):
            state["pending_confirm"] = scrub(state["pending_confirm"]) if access.interactions else {"restricted": True}
        return StreamSnapshot(cursor=cursor, state=state)

    async def read_stream(self, session_id: str, after_cursor: int, limit: int) -> list[dict]:
        """持久流从数据库顺序读取，Worker 事务桥可由任何订阅实例推进。"""
        log = SessionLog(session_id, self.session_factory)
        log.bridge_worker()
        return log.stream(after_cursor, min(limit, 500))

    async def read_trace(self, session_id: str, after_seq: int, limit: int) -> list[dict]:
        """调用者在 WS 层复验诊断 ACL，源事实脱敏由 trace_frame 完成。"""
        return SessionLog(session_id, self.session_factory).read(after_seq, limit=min(limit, 500))

    def _publish(self, session_id: str, payload: dict) -> None:
        """源 custom stream 只转发瞬态片段，所有持久事件统一经 PG 投影读取。"""
        kind = {"text": "assistant.text.delta", "reasoning": "assistant.reasoning.delta"}.get(payload.get("kind"))
        if kind is None:
            return
        data = {"text": payload.get("content", ""), "chunk_index": payload.get("chunk_index")}
        correlation = {key: payload[key] for key in ("turn", "step", "attempt_id") if key in payload}
        if "turn" in correlation:
            correlation["turn_id"] = f"{session_id}:{correlation['turn']}"
        envelope = frame(kind, data, session_id=session_id, correlation=correlation)
        observers = self._observers.get(session_id, {})
        for connection_id, (_actor, callback) in tuple(observers.items()):
            try:
                callback(envelope)
            except Exception:
                # 单个断线观察者不能使 Runtime 移除整个会话的广播订阅。
                observers.pop(connection_id, None)

    def _settings(self) -> LoopSettings:
        """运行限额与协议档参数分开，关闭思考必须由具体模型快照决定。"""
        return LoopSettings(dsh_max_steps=settings.agent_loop_max_steps,
                            dsh_model_max_retries=settings.agent_loop_model_max_retries,
                            dsh_model_retry_delay_seconds=settings.agent_loop_model_retry_delay_seconds,
                            dsh_max_parallel_tool_calls=settings.agent_loop_max_parallel_tool_calls,
                            dsh_approval_timeout_seconds=settings.agent_loop_approval_timeout_seconds)

    async def _entry(self, session_id: str, actor_id: str) -> _Entry:
        """仅创建运行时；写者必须在上一轮清理完成后由提交入口获取。"""
        entry = self.entries.get(session_id)
        if entry is not None:
            return entry
        log = SessionLog(session_id, self.session_factory, actor_id=actor_id)
        try:
            graph = await build_agent(self._settings())
            runtime = AgentRuntime(log, graph, approval_broker=self._broker,
                                   writer_id=log.writer_id, actor_id=actor_id)
            entry = _Entry(log, runtime)
            runtime.subscribe(lambda payload: self._publish(session_id, payload))
            self.entries[session_id] = entry
            return entry
        except BaseException:
            log.close()
            raise

    @staticmethod
    def _receipt(value: dict, fingerprint: str) -> CommandReceipt:
        """只有同一规范输入可以重用已提交回执。"""
        if value["fingerprint"] != fingerprint:
            raise AppError(ErrorCode.CONCURRENCY, "同一 request_id 对应不同命令")
        return CommandReceipt(value["data"], value.get("correlation", {}))

    async def execute_command(self, actor_id: str, connection_id: str, command) -> CommandReceipt:
        """会话命令串行受理；模型与工具任务始终在锁外后台运行。"""
        if self._closed:
            raise AppError(ErrorCode.VALIDATION, "服务正在关闭")
        await self.authorize(actor_id, command.session_id)
        lock = self._locks.setdefault(command.session_id, asyncio.Lock())
        async with lock:
            if self._closed:
                raise AppError(ErrorCode.VALIDATION, "服务正在关闭")
            readonly = SessionLog(command.session_id, self.session_factory)
            old = readonly.command_receipt(actor_id, command.request_id)
            if old:
                return self._receipt(old, command.fingerprint)
            if command.type == "turn.submit" and not settings.agent_loop_enabled:
                raise AppError(ErrorCode.VALIDATION, "Agent Loop 新回合放行已关闭")
            entry = await self._entry(command.session_id, actor_id)
            if command.type == "turn.submit":
                return await self._submit(entry, actor_id, connection_id, command)
            if entry.controller != (actor_id, connection_id):
                raise AppError(ErrorCode.UNAUTHORIZED, "当前连接不是该回合控制者")
            if command.type == "turn.cancel":
                expected = f"{command.session_id}:{entry.runtime.active_turn}"
                if command.data["turn_id"] != expected:
                    raise AppError(ErrorCode.CONCURRENCY, "回合已结束或不是当前回合")

                def cancel_fact(db, session, state):
                    correlation = {"turn": state.active_turn, "turn_id": expected}
                    entry.log._append(db, session, state, "runtime/cancel_requested", correlation)
                    return {"accepted": True, "turn_id": expected}, correlation

                receipt = entry.log.commit_command(actor_id, command.request_id, command.fingerprint, cancel_fact)
                await entry.runtime.cancel()
                return self._receipt(receipt, command.fingerprint)
            return self._respond(entry, actor_id, command)

    async def _submit(self, entry: _Entry, actor_id: str, connection_id: str, command) -> CommandReceipt:
        """回合边界重新取得写者并读取事实，空闲连接不占用 PG 连接池。"""
        claimed = False
        previous_cleanup = entry.cleanup
        try:
            if not entry.runtime.running:
                if previous_cleanup is not None:
                    # 新提交取消不能连带取消上一轮的资源清理。
                    await asyncio.shield(previous_cleanup)
                if self._closed:
                    raise AppError(ErrorCode.VALIDATION, "服务正在关闭")
                if entry.writer_released:
                    entry.log = SessionLog(command.session_id, self.session_factory, actor_id=actor_id)
                    entry.runtime.log = entry.log
                    entry.writer_released = False
                entry.log.claim()
                claimed = True
                entry.log.actor_id = actor_id
                entry.runtime.writer_id = entry.log.writer_id
                # 空闲期间可能由其他实例写入，恢复和模型预检都读取新句柄的持久事实。
                await entry.runtime.recover()
            return await self._submit_owned(entry, actor_id, connection_id, command)
        finally:
            # 幂等旧回执、预检/构造异常没有后台收尾任务，也必须归还本次 writer。
            if claimed and entry.cleanup is previous_cleanup and not entry.runtime.running:
                self._release_writer(entry)

    async def _submit_owned(self, entry: _Entry, actor_id: str, connection_id: str, command) -> CommandReceipt:
        """构造已授权依赖后原子提交输入，重复 client_message_id 不会创建新回合。"""
        data = command.data
        for event in entry.log.read():
            if event["type"] != "user/message" or event["data"].get("client_message_id") != data["client_message_id"]:
                continue
            previous = event["data"]
            context = event.get("extensions", {})
            if context.get("actor_id") != actor_id or context.get("input_fingerprint") != command.fingerprint:
                raise AppError(ErrorCode.CONCURRENCY, "client_message_id 已被其他输入使用")
            turn = previous["turn"]
            receipt = {"fingerprint": command.fingerprint, "data": {"accepted": True, "turn": turn, "turn_id": f"{command.session_id}:{turn}", "client_message_id": data["client_message_id"]}, "correlation": {"turn": turn}}
            entry.log.record_command(actor_id, command.request_id, receipt)
            return self._receipt(receipt, command.fingerprint)
        if entry.runtime.running:
            raise AppError(ErrorCode.CONCURRENCY, "会话已有活动回合")
        entry.log.actor_id = actor_id
        content = self._input_content(actor_id, data)
        dependencies, resources = await self._dependencies(entry, actor_id, {**data, "_model_content": content})
        context = {"request_id": command.request_id, "fingerprint": command.fingerprint,
                   "display_content": data["content"], "attachment_refs": data.get("attachment_refs", [])}
        try:
            if self._closed:
                raise AppError(ErrorCode.VALIDATION, "服务正在关闭")
            # 依赖装配可能等待 Runner 握手，提交输入前必须复验账号和会话权限。
            await self.authorize(actor_id, command.session_id)
            entry.controller = (actor_id, connection_id)
            self._bind_approval_owner(entry, actor_id, connection_id)
            effort = data.get("reasoning_effort")
            if effort is None and dependencies.request is not None:
                effort = dependencies.request.reasoning_effort
            await entry.runtime.submit(content, dependencies=dependencies, actor_id=actor_id,
                                       client_message_id=data["client_message_id"],
                                       reasoning_effort=effort, command_context=context)
        except BaseException:
            try:
                await self._close_resources(resources)
            finally:
                entry.controller = None
            raise
        entry.cleanup = asyncio.create_task(self._finish(entry, resources))
        receipt = entry.log.command_receipt(actor_id, command.request_id)
        if receipt is None:
            raise AppError(ErrorCode.INTERNAL, "输入提交缺少持久回执")
        return self._receipt(receipt, command.fingerprint)

    def _input_content(self, actor_id: str, data: dict):
        """附件按上传者验证并冻结到事实；本期内联读取，不隐式写工作区。"""
        from .attachments import (
            MAX_IMAGE_BYTES,
            build_model_content,
            load_message_files,
            normalize_attachment_refs,
        )

        refs = data.get("attachment_refs", [])
        if not refs:
            return data["content"]
        with self.session_factory() as db:
            normalize_attachment_refs(db, refs, owner_id=actor_id)
            files = load_message_files(db, refs, owner_id=actor_id)
            for row in files:
                path = Path(row.storage_path)
                if not path.is_file():
                    raise AppError(ErrorCode.NOT_FOUND, "附件内容不可读取")
                image = (row.content_type or "").startswith("image/") or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                if image and max(row.size_bytes, path.stat().st_size) > MAX_IMAGE_BYTES:
                    raise AppError(ErrorCode.VALIDATION, "图片超出模型附件限制")
            return build_model_content(data["content"], files)

    async def _wait_interaction(self, entry: _Entry, payload: dict):
        """卡已随 asked 事实提交；Future 仅承担本进程等待，不是持久授权事实。"""
        identity = payload["interaction_id"]
        future = asyncio.get_running_loop().create_future()
        entry.interactions[identity] = future
        try:
            # 卡落库与等待任务获得调度之间可能已收到回执；已提交答案优先于 Future。
            with self.session_factory() as db:
                session = db.get(Session, entry.log.session_id)
                card = session.pending_confirm if session is not None else None
                if card and card.get("interaction_id") == identity and card.get("response") is not None:
                    return card["response"]
            return await future
        finally:
            entry.interactions.pop(identity, None)

    def _respond(self, entry: _Entry, actor_id: str, command) -> CommandReceipt:
        """完整身份、nonce、有效期与答案校验在行锁事务内完成，提交后再唤醒。"""
        expected_kinds = {"approval.respond": "approval/asked", "question.respond": "question/asked", "task_confirmation.respond": "task_confirmation/requested"}
        data = command.data
        future = entry.interactions.get(data.get("interaction_id"))
        if future is not None and future.done():
            raise AppError(ErrorCode.CONCURRENCY, "交互已结束或不属于当前运行时")
        answer = None

        def respond(db, session, state):
            nonlocal answer
            card = session.pending_confirm or {}
            if session.pending_confirm_author_id != actor_id or card.get("kind") != expected_kinds.get(command.type):
                raise AppError(ErrorCode.UNAUTHORIZED, "无权处理该交互")
            if card.get("response") is not None or card.get("expires_at", 0) <= time.time():
                raise AppError(ErrorCode.CONCURRENCY, "交互已处理或超时")
            for key in ("interaction_id", "turn_id", "turn", "attempt_id", "call_id", "nonce"):
                if card.get(key) != data.get(key):
                    raise AppError(ErrorCode.VALIDATION, "交互身份不匹配")
            if state.active_turn != data["turn"]:
                raise AppError(ErrorCode.CONCURRENCY, "回合已结束")
            if command.type == "question.respond":
                from app.harness.execution.ask_user import validate_answers

                questions = card["questions"]
                by_id = {q["id"]: q for q in questions}
                normalized = []
                for item in data["answers"]:
                    question = by_id.get(item["question_id"], {})
                    value = item["answer"]
                    selected = [part.strip() for part in value.split(",") if part.strip()] if question.get("multi_select") or question.get("type") == "checkbox" else ([value] if value else [])
                    normalized.append({"id": item["question_id"], "custom": value, "selected": selected if question.get("options") else []})
                answer = {"answers": validate_answers(questions, normalized)}
            else:
                answer = data["decision"]
            if command.type == "task_confirmation.respond" and card.get("spec_hash") != data.get("spec_hash"):
                raise AppError(ErrorCode.VALIDATION, "确认规格已变化")
            session.pending_confirm = {**card, "response": answer}
            entry.log._append(db, session, state, "runtime/interaction_response", {"interaction_id": data["interaction_id"], "turn": data["turn"], "response": answer})
            return {"accepted": True, "interaction_id": data["interaction_id"]}, {key: data[key] for key in ("turn_id", "turn", "attempt_id", "call_id")}

        receipt = entry.log.commit_command(actor_id, command.request_id, command.fingerprint, respond)
        if future is not None and not future.done():
            future.set_result(answer)
        return self._receipt(receipt, command.fingerprint)

    async def detach(self, actor_id: str, session_id: str, connection_id: str) -> None:
        """只有当前控制连接断开才取消；观察者退出不影响执行。"""
        self._observers.get(session_id, {}).pop(connection_id, None)
        async with self._locks.setdefault(session_id, asyncio.Lock()):
            entry = self.entries.get(session_id)
            if entry is None:
                return
            if entry.approval_owner == (actor_id, connection_id):
                entry.runtime.clear_approval_gate(entry.approval_gate)
                entry.approval_owner = None
            if entry.controller == (actor_id, connection_id):
                await entry.runtime.cancel()

    def _bind_approval_owner(self, entry: _Entry, actor_id: str, connection_id: str) -> None:
        """同连接跨回合复用固定 gate；换连接或成员先废除旧 always，再注册。"""
        owner = (actor_id, connection_id)
        if entry.approval_owner == owner:
            return
        if entry.approval_gate is None:
            entry.approval_gate = lambda payload: self._wait_interaction(entry, payload)
        else:
            # gate 对象保持固定，必须显式注销才能在拥有者切换时撤回临时授权。
            entry.runtime.clear_approval_gate(entry.approval_gate)
        entry.runtime.set_approval_gate(entry.approval_gate, replace=True)
        entry.approval_owner = owner

    async def _finish(self, entry: _Entry, resources: list) -> None:
        """完整 drain 后归还 SDK 和 PG writer，保留同连接会话授权及持久 guard。"""
        try:
            await entry.runtime.wait()
        except Exception as exc:
            logger.warning("回合等待失败 type=%s", type(exc).__name__)
        finally:
            try:
                await self._close_resources(resources)
            finally:
                entry.controller = None
                if not entry.runtime.running:
                    self._release_writer(entry)

    @staticmethod
    def _release_writer(entry: _Entry) -> None:
        """日志关闭不可重用，下一轮换句柄但保留 Runtime 与审批 broker。"""
        entry.log.close()
        entry.runtime.writer_id = None
        entry.writer_released = True

    @staticmethod
    async def _close_resources(resources: list) -> None:
        """关闭本次装配拥有的资源，不关闭其他会话的客户端。"""
        from app.llm.resolver import close_adapter

        async def drain() -> None:
            """逆序尝试关闭全部资源；单个关闭失败不能遗留其他连接池。"""
            while resources:
                resource = resources.pop()
                try:
                    await close_adapter(resource)
                except (Exception, asyncio.CancelledError) as exc:
                    logger.warning("回合资源关闭失败 type=%s", type(exc).__name__)

        cleanup = asyncio.create_task(drain())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def close(self) -> None:
        """应用关闭时取消并结算运行时，最后释放 PG 写者连接。"""
        self._closed = True
        for session_id, entry in tuple(self.entries.items()):
            async with self._locks.setdefault(session_id, asyncio.Lock()):
                try:
                    await entry.runtime.close()
                except Exception as exc:
                    logger.warning("运行时关闭失败 type=%s", type(exc).__name__)
                finally:
                    if entry.cleanup:
                        await entry.cleanup
                    # 未完成 drain 时保留写者锁，不能给其他实例制造双执行窗口。
                    if not entry.runtime.running:
                        entry.log.close()
                        self.entries.pop(session_id, None)
        self._observers.clear()

    async def _dependencies(self, entry: _Entry, actor_id: str, data: dict) -> tuple[TurnDependencies, list]:
        """默认平台装配与注入测试使用同一 Runtime/Attempt/Store/ToolBridge。"""
        if self.dependency_builder is not None:
            return await self.dependency_builder(self, entry, actor_id, data)
        from .loop_wiring import build_dependencies

        return await build_dependencies(self, entry, actor_id, data)
