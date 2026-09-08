"""Agent Loop 的 PostgreSQL 事实存储：短事务内提交事实、投影和执行隔离。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from app.errors import AppError, ErrorCode
from app.models import (
    AgentEvent,
    AgentRuntimeState,
    Message,
    Session,
    SessionStream,
    Task,
    WorkspaceExecutionGuard,
    WsEvent,
)


class SessionLogWriteError(OSError):
    """事实无法提交；上层必须停止当前执行而非继续派发。"""


def _key(kind: str, data: dict) -> str | None:
    """为不可重复的语义边界生成幂等键，其余事实按顺序独立追加。"""
    if kind in {
        "approval/asked", "approval/decided", "question/asked", "question/answered",
        "task_confirmation/requested", "task_confirmation/resolved",
    }:
        identity = data.get("interaction_id") or data.get("approval_id") or data.get("id")
        return f"{kind}:{identity}" if identity else None
    if kind == "task/queued" and data.get("call_id"):
        return f"{kind}:{data.get('turn')}:{data.get('attempt_id')}:{data['call_id']}"
    if kind == "runtime/cancel_requested":
        return f"{kind}:{data.get('turn')}"
    if kind.startswith("tool/") and data.get("call_id"):
        return f"{kind}:{data.get('turn')}:{data.get('attempt_id')}:{data['call_id']}"
    if kind in {"turn/start", "turn/end", "user/message"}:
        return f"{kind}:{data.get('turn')}"
    if kind in {"step/start", "step/end"}:
        return f"{kind}:{data.get('turn')}:{data.get('step')}"
    if kind in {"assistant/message", "assistant/attempt", "assistant/attempt_start"}:
        return f"{kind}:{data.get('attempt_id')}"
    return None


def canonical_scope(path: str) -> str:
    """目录隔离使用规范真实路径，避免同目录不同拼写绕过冲突检查。"""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def scopes_overlap(left: str, right: str) -> bool:
    """按路径段判断祖先/子目录重叠，不使用易误判的字符串前缀。"""
    try:
        return os.path.commonpath((left, right)) in (left, right)
    except ValueError:
        return False


class SessionLog:
    """与源 SessionLog 同形的持久端口，生产写者由 PG 会话 advisory lock 排他。"""

    def __init__(self, session_id: str, session_factory=None, *, actor_id: str | None = None):
        """绑定会话事实端口，构造本身不抢占 writer 或恢复其他实例的回合。"""
        if session_factory is None:
            from app.db import SessionLocal

            session_factory = SessionLocal
        self.session_id = session_id
        self.session_factory = session_factory
        self.actor_id = actor_id
        self.writer_id: str | None = None
        self.command_context: dict[str, Any] = {}
        self._owner_connection = None
        self._owner_pid: int | None = None
        self._lock = threading.RLock()
        self._closed = False

    def claim(self, writer_id: str | None = None) -> None:
        """持有专用 PG 连接的会话锁；进程退出后数据库自动释放，不能按超时抢占。"""
        with self._lock:
            if self._closed:
                raise SessionLogWriteError("会话事实端口已关闭")
            if self._owner_connection is not None:
                if self._owner_connection.closed or self._owner_connection.invalidated:
                    raise SessionLogWriteError("原写者连接已失效，必须创建新日志句柄")
                if writer_id is not None and writer_id != self.writer_id:
                    raise AppError(ErrorCode.CONCURRENCY, "不能更换已持有的 writer 身份")
                return
            with self.session_factory() as db:
                engine = db.get_bind()
            connection = engine.connect()
            try:
                acquired = connection.execute(text(
                    "SELECT pg_try_advisory_lock(hashtextextended(:sid, 721903))"
                ), {"sid": self.session_id}).scalar_one()
                connection.commit()
                if not acquired:
                    raise AppError(ErrorCode.CONCURRENCY, "会话正在其他实例执行，请连接会话所属实例")
                self._owner_connection = connection
                self._owner_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
                connection.commit()
                self.writer_id = writer_id or str(uuid.uuid4())
                with self._transaction(check_writer=False) as (db, _session, state):
                    state.writer_id = self.writer_id
            except BaseException:
                # 异常连接不能带着会话锁回到池中；物理断开使 PG 释放所有锁。
                connection.invalidate()
                self._owner_connection = None
                self._owner_pid = None
                self.writer_id = None
                connection.close()
                raise

    @contextmanager
    def _transaction(self, *, guard: bool = False, check_writer: bool = True):
        """锁顺序固定为 guard 注册表→session；序号随提交整体回滚。"""
        with self._lock, self.session_factory() as db, db.begin():
            if self._closed:
                raise SessionLogWriteError("会话事实端口已关闭")
            if check_writer:
                connection = self._owner_connection
                if not self.writer_id or connection is None:
                    raise AppError(ErrorCode.CONCURRENCY, "当前运行时不持有会话写入权")
                if connection.closed or connection.invalidated:
                    raise SessionLogWriteError("持久 writer 连接已失效")
                # 本事务直接使用持有 advisory lock 的物理连接，不存在探活后另连写入的窗口。
                db.bind = connection
                if db.execute(text("SELECT pg_backend_pid()")).scalar_one() != self._owner_pid:
                    raise SessionLogWriteError("持久 writer 连接身份已变化")
            if guard:
                db.execute(text("SELECT pg_advisory_xact_lock(721904)"))
            session = db.execute(select(Session).where(Session.id == self.session_id).with_for_update()).scalar_one_or_none()
            if session is None or session.deleted_at is not None:
                raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
            if session.engine_version != "agent_loop_v2":
                raise AppError(ErrorCode.VALIDATION, "会话未启用 Agent Loop v2")
            state = db.get(AgentRuntimeState, self.session_id)
            if state is None:
                state = AgentRuntimeState(session_id=self.session_id, next_seq=0, last_cursor=0, last_turn=0, worker_event_id=0)
                db.add(state)
                db.flush()
            if check_writer and (not self.writer_id or state.writer_id != self.writer_id):
                raise AppError(ErrorCode.CONCURRENCY, "当前运行时不持有会话写入权")
            yield db, session, state

    @property
    def next_seq(self) -> int:
        """下一事实序号，空日志为零；读取不占号。"""
        with self.session_factory() as db:
            state = db.get(AgentRuntimeState, self.session_id)
            return state.next_seq if state else 0

    def read(
        self, after_seq: int = -1, *, limit: int | None = None, through: int | None = None,
    ) -> list[dict[str, Any]]:
        """读取已提交事实的独立副本，调用者不能修改持久历史。"""
        with self.session_factory() as db:
            query = select(AgentEvent.envelope).where(
                AgentEvent.session_id == self.session_id, AgentEvent.seq > after_seq
            ).order_by(AgentEvent.seq)
            if through is not None:
                query = query.where(AgentEvent.seq <= through)
            if limit is not None:
                if type(limit) is not int or limit < 1:
                    raise ValueError("limit 必须为正整数")
                query = query.limit(min(limit, 1000))
            rows = db.execute(query).scalars().all()
            return deepcopy(list(rows))

    def append(self, type: str, data: dict[str, Any], **metadata) -> dict[str, Any]:
        """事实、正文读模型、卡和 WS v2 投影同事务提交后才返回。"""
        with self._transaction(guard=type in {"tool/dispatch", "tool/result", "execution/reconciled"}) as (db, session, state):
            return self._append(db, session, state, type, data, **metadata)

    def _append(self, db, session, state, kind: str, data: dict, **metadata) -> dict:
        """内部事务复用点；禁止在这里提交，从而允许成组事实原子落库。"""
        from app.agent.events import (
            correlation_from_data,
            event_schema_descriptor,
            producer_for_event_type,
            project_fact,
        )

        value = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
        logical_key = metadata.pop("logical_key", None) or _key(kind, value)
        if logical_key:
            previous = db.execute(select(AgentEvent).where(AgentEvent.session_id == self.session_id, AgentEvent.logical_key == logical_key)).scalar_one_or_none()
            if previous:
                if previous.envelope["data"] != value:
                    raise AppError(ErrorCode.CONCURRENCY, "同一事件身份对应不同数据")
                return deepcopy(previous.envelope)
        seq = state.next_seq
        if kind == "user/message":
            metadata["extensions"] = {**metadata.get("extensions", {}), "actor_id": self.actor_id,
                                      "input_fingerprint": self.command_context.get("fingerprint"),
                                      "client_message_id": value.get("client_message_id"),
                                      "request_id": self.command_context.get("request_id"),
                                      "display_content": self.command_context.get("display_content"),
                                      "attachment_refs": self.command_context.get("attachment_refs", [])}
        event = {
            "schema_version": 2, "event_version": metadata.get("event_version", 1),
            "event_id": f"evt-{self.session_id}-{seq}", "session_id": self.session_id,
            "seq": seq, "ts": time.time(), "type": kind,
            "producer": metadata.get("producer", producer_for_event_type(kind)), "durability": "committed",
            "correlation": metadata.get("correlation", correlation_from_data(value)),
            "schema": event_schema_descriptor(kind, metadata.get("event_version", 1)),
            "data": value, "extensions": metadata.get("extensions", {}),
        }
        if "turn" in value:
            event["correlation"]["turn_id"] = f"{self.session_id}:{value['turn']}"
        quarantined = []
        if kind == "tool/dispatch":
            self._guard_dispatch(db, value)
        elif kind == "tool/result":
            statuses = {"succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown"}
            if value.get("status") not in statuses:
                raise AppError(ErrorCode.VALIDATION, "非法工具结果状态")
            if "is_error" in value and value["is_error"] != (value["status"] != "succeeded"):
                raise AppError(ErrorCode.VALIDATION, "工具结果状态与 is_error 不一致")
            if value.get("call_seq") is not None:
                call = db.execute(select(AgentEvent).where(
                    AgentEvent.session_id == self.session_id, AgentEvent.seq == value["call_seq"],
                    AgentEvent.type == "tool/call",
                )).scalar_one_or_none()
                if call is None or any(
                    call.envelope["data"].get(key) != value.get(key)
                    for key in ("turn", "attempt_id", "call_id", "name")
                ):
                    raise AppError(ErrorCode.VALIDATION, "工具结果引用了错误的调用事实")
            guards = db.execute(select(WorkspaceExecutionGuard).where(WorkspaceExecutionGuard.session_id == self.session_id, WorkspaceExecutionGuard.attempt_id == value.get("attempt_id"), WorkspaceExecutionGuard.call_id == value.get("call_id"))).scalars()
            for guard in guards:
                if guard.evidence.get("engine") == "legacy" or guard.evidence.get("turn") != value.get("turn"):
                    continue
                if guard.evidence.get("call_seq") != value.get("call_seq"):
                    raise AppError(ErrorCode.VALIDATION, "结果缺少原始派发调用序号")
                if guard.status == "released":
                    continue
                if guard.evidence.get("runner_instance_id") and value["status"] != "outcome_unknown":
                    self._validate_evidence(guard, {**value.get("metadata", {}), "status": value["status"]})
                guard.status = "quarantined" if value.get("status") == "outcome_unknown" else "released"
                guard.evidence = {**guard.evidence, "source_seq": seq, "status": value.get("status"),
                                  "result_metadata": value.get("metadata", {})}
                if guard.status == "quarantined":
                    quarantined.append(guard.execution_id)
        elif kind == "execution/reconciled":
            guard = db.get(WorkspaceExecutionGuard, value.get("execution_id"))
            if (
                guard is None or guard.session_id != self.session_id or guard.status != "released"
                or not value.get("evidence") or guard.evidence.get("reconciliation") != value["evidence"]
            ):
                raise AppError(ErrorCode.VALIDATION, "对账事实必须随可信 guard 结算一起提交")
        if kind == "turn/start":
            if state.active_turn is not None:
                raise AppError(ErrorCode.CONCURRENCY, "会话已有活动回合")
            state.active_turn = value["turn"]
            state.last_turn = max(state.last_turn, value["turn"])
        elif kind == "turn/end":
            if state.active_turn == value["turn"]:
                state.active_turn = None
        state.next_seq += 1
        session.updated_at = datetime.now(UTC)
        db.add(AgentEvent(session_id=self.session_id, seq=seq, type=kind, logical_key=logical_key, envelope=event))
        self._project_message(db, event)
        self._project_card(session, event)
        projection_event = deepcopy(event)
        if kind == "user/message":
            projection_event["data"].update(
                author_id=self.actor_id,
                attachment_refs=event["extensions"]["attachment_refs"],
            )
            if event["extensions"].get("display_content") is not None:
                projection_event["data"]["display_content"] = event["extensions"]["display_content"]
        for frame in project_fact(projection_event):
            self._stream_frame(db, state, frame, source_kind="agent", source_id=event["event_id"])
        db.flush()
        for execution_id in quarantined:
            self._append(db, session, state, "execution/quarantined", {
                "execution_id": execution_id, "reason": "outcome_unknown",
                **{key: value[key] for key in ("turn", "step", "attempt_id", "call_id") if key in value},
            }, logical_key=f"quarantine:{execution_id}")
        return deepcopy(event)

    def _stream_frame(self, db, state, frame: dict, *, source_kind: str, source_id: str) -> None:
        """只在持有 session 行锁时分配连续已提交游标。"""
        if db.execute(select(SessionStream.id).where(
            SessionStream.session_id == self.session_id, SessionStream.source_kind == source_kind,
            SessionStream.source_id == source_id, SessionStream.projection_kind == frame["type"],
        )).first():
            return
        state.last_cursor += 1
        frame = {**frame, "cursor": state.last_cursor}
        frame.pop("projection_kind", None)
        db.add(SessionStream(session_id=self.session_id, cursor=state.last_cursor, source_kind=source_kind, source_id=source_id, projection_kind=frame["type"], envelope=frame))

    def _project_message(self, db, event: dict) -> None:
        """REST 正文是事实的读模型，不能反向成为模型工具历史。"""
        kind, data = event["type"], event["data"]
        if kind not in {"user/message", "assistant/message"}:
            return
        payload = data.get("message", data)
        content = payload.get("content", "")
        role = "user" if kind == "user/message" else "assistant"
        extensions = event["extensions"]
        if isinstance(content, list):
            content = extensions.get("display_content") or "\n".join(
                block["text"] for block in content if isinstance(block, dict)
                and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
        elif not isinstance(content, str):
            content = ""
        db.add(Message(session_id=self.session_id, role=role, content=content,
                       source_id=event["event_id"], source_version=1,
                       attachments=extensions.get("attachment_refs", []) if role == "user" else [],
                       author_id=self.actor_id if role == "user" else None,
                       client_message_id=data.get("client_message_id") if role == "user" else None))

    def begin_turn(self, user_data: dict, *, writer_id: str | None = None) -> tuple[dict, dict]:
        """接受回合与用户事实原子写入；没有半个已接受回合。"""
        with self._transaction() as (db, session, state):
            if writer_id is not None and writer_id != self.writer_id:
                raise AppError(ErrorCode.CONCURRENCY, "输入 writer 身份不匹配")
            command = self.command_context
            previous = None
            client_id = user_data.get("client_message_id")
            if client_id:
                previous = db.execute(select(AgentEvent).where(
                    AgentEvent.session_id == self.session_id, AgentEvent.type == "user/message",
                    AgentEvent.envelope["data"]["client_message_id"].astext == client_id,
                )).scalar_one_or_none()
            if command.get("request_id"):
                if not self.actor_id or not command.get("fingerprint"):
                    raise AppError(ErrorCode.VALIDATION, "命令缺少成员或输入指纹")
                key = self._command_key(self.actor_id, command["request_id"])
                receipt = db.execute(select(AgentEvent).where(
                    AgentEvent.session_id == self.session_id, AgentEvent.logical_key == key,
                )).scalar_one_or_none()
                if receipt:
                    if receipt.envelope["data"]["fingerprint"] != command["fingerprint"]:
                        raise AppError(ErrorCode.CONCURRENCY, "同一请求 ID 对应不同输入")
                    previous = db.execute(select(AgentEvent).where(
                        AgentEvent.session_id == self.session_id,
                        AgentEvent.logical_key == f"user/message:{receipt.envelope['data']['data']['turn']}",
                    )).scalar_one()
            if previous:
                old = previous.envelope
                if (
                    {k: v for k, v in old["data"].items() if k != "turn"}
                    != {k: v for k, v in user_data.items() if k != "turn"}
                    or old["extensions"].get("actor_id") != self.actor_id
                    or old["extensions"].get("input_fingerprint") != command.get("fingerprint")
                ):
                    raise AppError(ErrorCode.CONCURRENCY, "client_message_id 对应不同输入")
                turn = old["data"]["turn"]
                started = db.execute(select(AgentEvent).where(
                    AgentEvent.session_id == self.session_id,
                    AgentEvent.logical_key == f"turn/start:{turn}",
                )).scalar_one().envelope
                message = old
            else:
                turn = state.last_turn + 1
                if user_data.get("turn", turn) != turn:
                    raise AppError(ErrorCode.CONCURRENCY, "回合序号已变化")
                started = self._append(db, session, state, "turn/start", {"turn": turn})
                message = self._append(db, session, state, "user/message", {**user_data, "turn": turn})
            if command.get("request_id"):
                receipt = {"fingerprint": command["fingerprint"], "data": {
                    "accepted": True, "turn_id": f"{self.session_id}:{turn}", "turn": turn,
                    "client_message_id": user_data.get("client_message_id"),
                }, "correlation": {"turn": turn, "turn_id": f"{self.session_id}:{turn}"}}
                self._append(db, session, state, "runtime/command", receipt,
                             logical_key=self._command_key(self.actor_id, command["request_id"]))
            return deepcopy(started), deepcopy(message)

    def _project_card(self, session, event: dict) -> None:
        """新审批/澄清卡与源事实一起提交，不借用旧 GraphInterrupt 恢复。"""
        kind, data = event["type"], event["data"]
        asked = {"approval/asked", "question/asked", "task_confirmation/requested"}
        decided = {"approval/decided", "question/answered", "task_confirmation/resolved"}
        if kind in asked:
            if not data.get("interaction_id"):
                raise AppError(ErrorCode.VALIDATION, "交互缺少稳定身份")
            if session.pending_confirm:
                raise AppError(ErrorCode.CONCURRENCY, "会话存在尚未结算的交互")
            session.pending_confirm = {**data, "engine_version": "agent_loop_v2", "kind": kind,
                                       "turn_id": f"{self.session_id}:{data['turn']}", "schema_version": 3}
            session.pending_confirm_author_id = self.actor_id
        elif kind in decided and session.pending_confirm:
            card = session.pending_confirm
            pairs = {"approval/decided": "approval/asked", "question/answered": "question/asked",
                     "task_confirmation/resolved": "task_confirmation/requested"}
            matches = (
                card.get("engine_version") == "agent_loop_v2"
                and card.get("kind") == pairs[kind]
                and card.get("interaction_id") == data.get("interaction_id")
                and all(card.get(key) == data.get(key) for key in ("turn", "attempt_id", "call_id"))
                and card.get("nonce") == data.get("nonce")
            )
            if matches:
                session.pending_confirm = None
                session.pending_confirm_author_id = None
            else:
                raise AppError(ErrorCode.CONCURRENCY, "交互结算不属于当前卡片")

    def snapshot(self) -> tuple[int, dict]:
        """在同一会话锁下取高水位及由事实维护的快照，快照不执行任何副作用。"""
        with self._transaction(check_writer=False) as (db, session, state):
            # 消息顺序由源 seq 决定，不能由同事务时间戳及随机 UUID 决定。
            messages = db.execute(select(Message).join(
                AgentEvent, (AgentEvent.session_id == Message.session_id)
                & (AgentEvent.envelope["event_id"].astext == Message.source_id),
            ).where(Message.session_id == self.session_id).order_by(AgentEvent.seq)).scalars()
            readmodels: dict[str, dict[tuple, dict]] = {
                "tools": {}, "tasks": {}, "turns": {}, "steps": {}, "assistants": {}, "executions": {},
            }
            frames = db.scalars(select(SessionStream.envelope).where(
                SessionStream.session_id == self.session_id,
                SessionStream.cursor <= state.last_cursor,
            ).order_by(SessionStream.cursor))
            for envelope in frames:
                kind = envelope["type"]
                correlation, data = envelope["correlation"], envelope["data"]
                family = kind.partition(".")[0]
                mapping = {
                    "tool": ("tools", ("turn", "attempt_id", "call_id")),
                    "task": ("tasks", ("task_id",)),
                    "turn": ("turns", ("turn",)),
                    "step": ("steps", ("turn", "step")),
                    "assistant": ("assistants", ("turn", "attempt_id")),
                    "execution": ("executions", ("execution_id",)),
                }
                if family not in mapping:
                    continue
                group, keys = mapping[family]
                values = {**correlation, **data}
                identity = tuple(values.get(key) for key in keys)
                if any(value is None for value in identity):
                    continue
                record = readmodels[group].setdefault(identity, {})
                record.update(deepcopy(values))
                record["cursor"] = envelope["cursor"]
                record["event"] = kind
                if kind == "tool.call":
                    record["status"] = "pending"
                elif kind == "tool.dispatch":
                    record["status"] = "running"
                elif kind == "task.queued":
                    record.setdefault("status", "queued")
            return state.last_cursor, {
                "engine_version": session.engine_version,
                "active_turn": state.active_turn,
                "pending_confirm": deepcopy(session.pending_confirm),
                "messages": [{"id": row.id, "role": row.role, "content": row.content,
                              "client_message_id": row.client_message_id, "author_id": row.author_id,
                              "attachment_refs": deepcopy(row.attachments)} for row in messages],
                **{name: list(records.values()) for name, records in readmodels.items()},
            }

    def _guard_dispatch(self, db, data: dict) -> None:
        """dispatch 与 scope 隔离一起提交，远端失联也不会释放工作区。"""
        scope = data.get("scope_path")
        if not scope:
            return
        scope = canonical_scope(scope)
        access = data.get("access", "write")
        if access not in {"read", "write"} or not all(
            data.get(key) for key in ("execution_id", "attempt_id", "call_id")
        ):
            raise AppError(ErrorCode.VALIDATION, "派发缺少合法执行身份或访问模式")
        rows = db.execute(select(WorkspaceExecutionGuard).where(WorkspaceExecutionGuard.status != "released")).scalars()
        for current in rows:
            if scopes_overlap(scope, current.scope_path) and (current.status == "quarantined" or access != "read" or current.access != "read"):
                raise AppError(ErrorCode.CONCURRENCY, "工作区存在运行中或结果未知的冲突执行")
        if not self.actor_id:
            raise AppError(ErrorCode.VALIDATION, "执行缺少已认证成员身份")
        db.add(WorkspaceExecutionGuard(execution_id=data["execution_id"], session_id=self.session_id,
                                      scope_path=scope, access=access, status="active",
                                      attempt_id=data["attempt_id"], call_id=data["call_id"], owner_id=self.actor_id,
                                      evidence={key: data[key] for key in (
                                          "turn", "step", "call_seq", "runner_instance_id",
                                          "request_fingerprint", "runner_request_payload",
                                      ) if key in data}))

    def stream(self, after_cursor: int = 0, limit: int = 500, *, through: int | None = None) -> list[dict]:
        """按数据库提交顺序分页，通知顺序和 agent seq 均不参与排序。"""
        if type(limit) is not int or limit < 1:
            raise ValueError("limit 必须为正整数")
        with self.session_factory() as db:
            query = select(SessionStream.envelope).where(SessionStream.session_id == self.session_id, SessionStream.cursor > after_cursor)
            if through is not None:
                query = query.where(SessionStream.cursor <= through)
            return deepcopy(list(db.execute(query.order_by(SessionStream.cursor).limit(min(limit, 1000))).scalars()))

    def high_water(self) -> int:
        """取已提交流的高水位，不分配游标。"""
        with self.session_factory() as db:
            state = db.get(AgentRuntimeState, self.session_id)
            return state.last_cursor if state else 0

    def command_receipt(self, actor_id: str, request_id: str) -> dict | None:
        """从持久事实读取命令收据，跨断连和重启去重。"""
        key = self._command_key(actor_id, request_id)
        with self.session_factory() as db:
            row = db.execute(select(AgentEvent).where(AgentEvent.session_id == self.session_id, AgentEvent.logical_key == key)).scalar_one_or_none()
            return deepcopy(row.envelope["data"]) if row else None

    @staticmethod
    def _command_key(actor_id: str, request_id: str) -> str:
        """成员与请求 ID 一起限定命令幂等域。"""
        return "command:" + hashlib.sha256(f"{actor_id}\0{request_id}".encode()).hexdigest()

    def record_command(self, actor_id: str, request_id: str, data: dict) -> dict:
        """记录已结算的命令结果；发起副作用时须在所属事实事务内调用。"""
        return self.append("runtime/command", data, logical_key=self._command_key(actor_id, request_id))

    def commit_command(self, actor_id: str, request_id: str, fingerprint: str, mutate) -> dict:
        """命令数据、nonce 消费与回执共用事务；外部副作用只在提交后触发。"""
        key = self._command_key(actor_id, request_id)
        with self._transaction() as (db, session, state):
            old = db.execute(select(AgentEvent).where(AgentEvent.session_id == self.session_id, AgentEvent.logical_key == key)).scalar_one_or_none()
            if old:
                result = old.envelope["data"]
                if result["fingerprint"] != fingerprint:
                    raise AppError(ErrorCode.CONCURRENCY, "同一请求 ID 不能对应不同命令")
                return deepcopy(result)
            data, correlation = mutate(db, session, state)
            receipt = {"fingerprint": fingerprint, "data": data, "correlation": correlation}
            self._append(db, session, state, "runtime/command", receipt, logical_key=key)
            return receipt

    def _has_task_frame(self, db, task_id: str, kind: str, report_id: str | None = None) -> bool:
        """任务终态及报告以稳定业务身份去重，允许 outbox 延迟到达。"""
        query = select(SessionStream.id).where(
            SessionStream.session_id == self.session_id, SessionStream.projection_kind == kind,
            SessionStream.envelope["correlation"]["task_id"].astext == task_id,
        )
        if report_id is not None:
            query = query.where(SessionStream.envelope["data"]["report_id"].astext == report_id)
        return db.execute(query.limit(1)).first() is not None

    def bridge_worker(self, limit: int = 200) -> None:
        """事务桥接 outbox，并用持久任务终态补齐 Worker 未发布或丢失的结束事件。"""
        from app.agent.events import frame

        if type(limit) is not int or limit < 1:
            raise ValueError("limit 必须为正整数")
        with self._transaction(check_writer=False) as (db, _session, state):
            rows = list(db.scalars(select(WsEvent).where(
                WsEvent.session_id == self.session_id, WsEvent.event_id > state.worker_event_id,
            ).order_by(WsEvent.event_id).limit(min(limit, 1000))))
            for row in rows:
                payload, kind = row.payload or {}, None
                status = payload.get("status")
                if row.task_id:
                    if row.event == "progress":
                        kind = "task.progress"
                    elif row.event == "report":
                        kind = "task.report"
                    elif row.event == "task_cancelled":
                        kind, status = "task.end", "cancelled"
                    elif row.event == "task_state":
                        kind = "task.end" if status in {"succeeded", "failed", "cancelled"} else "task.progress"
                    elif row.event == "error":
                        kind = "task.progress"
                if kind:
                    ended = self._has_task_frame(db, row.task_id, "task.end")
                    duplicate_report = kind == "task.report" and self._has_task_frame(
                        db, row.task_id, kind, payload.get("report_id"),
                    )
                    if not duplicate_report and not (ended and kind in {"task.progress", "task.end"}):
                        data = {key: payload[key] for key in ("report_id", "display") if key in payload}
                        if kind == "task.progress":
                            progress = payload.get("progress")
                            data["progress"] = progress if isinstance(progress, dict) else {
                                key: payload[key] for key in ("percent", "done", "total", "message", "code")
                                if key in payload
                            }
                            task = db.get(Task, row.task_id)
                            if (
                                not status and task is not None and task.session_id == self.session_id
                                and task.status in {"queued", "running", "awaiting_case_confirm"}
                            ):
                                status = task.status
                        if status:
                            data["status"] = status
                        self._stream_frame(
                            db, state, frame(kind, data, session_id=self.session_id, cursor=1,
                                             correlation={"task_id": row.task_id}, ts=row.ts.timestamp()),
                            source_kind="worker", source_id=str(row.id),
                        )
                state.worker_event_id = row.event_id
            # 一个有界批次尚未追平 outbox 时不提前结束，保证已提交进展先于终态。
            if db.execute(select(WsEvent.id).where(
                WsEvent.session_id == self.session_id, WsEvent.event_id > state.worker_event_id,
            ).limit(1)).first():
                return
            tasks = db.scalars(select(Task).where(
                Task.session_id == self.session_id, Task.status.in_(("succeeded", "failed", "cancelled")),
            ).order_by(Task.finished_at, Task.id))
            for task in tasks:
                # Task.report_id 与终态在 Worker 同事务提交，报告 WS 消息可以晚到或丢失。
                if task.report_id and not self._has_task_frame(db, task.id, "task.report", task.report_id):
                    self._stream_frame(
                        db, state, frame("task.report", {"report_id": task.report_id},
                                         session_id=self.session_id, cursor=1, correlation={"task_id": task.id}),
                        source_kind="task", source_id=f"{task.id}:report:{task.report_id}",
                    )
                if not self._has_task_frame(db, task.id, "task.end"):
                    self._stream_frame(
                        db, state, frame("task.end", {
                            "status": task.status, **({"report_id": task.report_id} if task.report_id else {}),
                        }, session_id=self.session_id, cursor=1, correlation={"task_id": task.id}),
                        source_kind="task", source_id=task.id,
                    )

    @staticmethod
    def _validate_evidence(guard, evidence: dict) -> None:
        """只接受绑定同一执行、runner 实例和请求的内部停止收据。"""
        if (
            not isinstance(evidence, dict)
            or evidence.get("execution_id") != guard.execution_id
            or evidence.get("process_tree_terminated") is not True
            or evidence.get("status") not in {"succeeded", "failed", "cancelled", "not_started", "denied"}
            or evidence.get("termination_evidence") not in {"not_started", "cgroup_empty"}
        ):
            raise AppError(ErrorCode.VALIDATION, "缺少同一执行的可信停止证据")
        tombstone = (
            evidence.get("termination_evidence") == "not_started"
            and evidence.get("execution_started") is False
            and evidence.get("request_fingerprint") is None
        )
        if evidence["termination_evidence"] == "not_started" and not tombstone:
            raise AppError(ErrorCode.VALIDATION, "未启动收据缺少明确的未执行声明")
        for key in ("runner_instance_id", "request_fingerprint"):
            if key == "request_fingerprint" and tombstone:
                continue
            if guard.evidence.get(key) and guard.evidence[key] != evidence.get(key):
                raise AppError(ErrorCode.VALIDATION, "停止证据不属于原始执行")

    def reconcile_execution(self, execution_id: str, evidence: dict) -> None:
        """内部服务用可信收据原子解除隔离并保留完整审计证据。"""
        with self._transaction(guard=True) as (db, session, state):
            guard = db.get(WorkspaceExecutionGuard, execution_id)
            if guard is None or guard.session_id != self.session_id:
                raise AppError(ErrorCode.NOT_FOUND, "执行记录不存在")
            self._validate_evidence(guard, evidence)
            if guard.status == "released":
                return
            guard.status = "released"
            guard.evidence = {**guard.evidence, "reconciliation": deepcopy(evidence)}
            self._append(db, session, state, "execution/reconciled", {
                "execution_id": execution_id, "outcome": evidence.get("status"),
                "evidence": deepcopy(evidence),
            }, logical_key=f"reconcile:{execution_id}")

    def close(self) -> None:
        """关闭专用连接释放 writer 锁；断连清理不重连，隔离记录独立保留。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connection = self._owner_connection
            try:
                if connection is not None and not connection.closed and not connection.invalidated:
                    try:
                        connection.execute(text(
                            "SELECT pg_advisory_unlock(hashtextextended(:sid, 721903))"
                        ), {"sid": self.session_id})
                        connection.commit()
                    except Exception:
                        connection.invalidate()
            finally:
                if connection is not None:
                    connection.close()
                self._owner_connection = None
                self._owner_pid = None
                self.writer_id = None
