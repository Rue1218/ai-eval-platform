"""基于 LangGraph Agent 的 WebSocket 单轮对话入口。

本路由只负责短票鉴权、会话事件持久化和流式传输；Agent 图负责单轮模型调用。
工具、人工确认、长任务和 Harness 运行时暂不在本轮恢复，避免旧框架重新混入。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..adapters import StreamAborted
from ..agent import LangGraphAgent
from ..db import SessionLocal
from ..errors import AppError, ErrorCode
from ..llm import ModelConfig, ModelRequest, ModelResponse
from ..models import Message, ProtocolProfile, Setting, User, WsEvent
from ..models import Session as AgentSession
from ..security import TOKEN_TYPE_WS, decode_token
from ..session_access import require_visible_session
from ..session_connections import SESSION_CONNECTION_HUB
from .profiles import _profile_connection

router = APIRouter(tags=["ws"])
logger = logging.getLogger("ai-eval.agent-ws")

_AGENT = LangGraphAgent()
_USED_WS_TICKETS: set[str] = set()
_TICKET_LOCK = threading.Lock()


class _ConnectionState:
    """单个 WebSocket 连接的发送锁与事件游标。"""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.cursor = 0


def _iso(value: datetime | None = None) -> str:
    """将数据库时间统一转换为前端可解析的 UTC ISO 字符串。"""
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _frame(
    session_id: str,
    event: str,
    event_id: int,
    payload: dict[str, Any],
    *,
    task_id: str | None = None,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """构造 API.md §4.2 规定的 WebSocket 公共事件头。"""
    return {
        "event": event,
        "session_id": session_id,
        "task_id": task_id,
        "event_id": event_id,
        "ts": _iso(ts),
        "payload": payload,
    }


async def _send(
    websocket: WebSocket,
    state: _ConnectionState,
    frame: dict[str, Any],
) -> bool:
    """串行发送一帧；连接已关闭时只返回失败，不把底层异常泄露给前端。"""
    try:
        async with state.lock:
            await websocket.send_json(frame)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False
    except Exception as exc:
        logger.info("Agent WS 发送失败 type=%s", type(exc).__name__)
        return False


def _consume_ws_ticket(db: Session, ticket: str | None) -> User:
    """校验并消费五分钟单次短票；所有失败统一由调用方关闭为 4401。"""
    if not ticket:
        raise AppError(ErrorCode.UNAUTHORIZED, "WebSocket 短票无效", status_code=401)
    try:
        payload = decode_token(ticket)
    except Exception as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, "WebSocket 短票无效", status_code=401) from exc
    if payload.get("type") != TOKEN_TYPE_WS or not payload.get("jti"):
        raise AppError(ErrorCode.UNAUTHORIZED, "WebSocket 短票无效", status_code=401)

    jti = str(payload["jti"])
    with _TICKET_LOCK:
        if jti in _USED_WS_TICKETS:
            raise AppError(ErrorCode.UNAUTHORIZED, "WebSocket 短票已使用", status_code=401)
        _USED_WS_TICKETS.add(jti)

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or user.disabled or payload.get("av") != user.auth_version:
        raise AppError(ErrorCode.UNAUTHORIZED, "用户不可用", status_code=401)
    return user


def _next_event_id(db: Session, session_id: str) -> int:
    """计算会话内下一个单调事件号；当前 API 单副本同步事务内无 await。"""
    row = (
        db.query(WsEvent.event_id)
        .filter(WsEvent.session_id == session_id)
        .order_by(WsEvent.event_id.desc())
        .first()
    )
    return int(row[0]) + 1 if row else 1


async def _emit_persistent(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    event: str,
    payload: dict[str, Any],
    *,
    task_id: str | None = None,
) -> bool:
    """写入 ws_events 并发送持久化事件；事件号由数据库历史决定。"""
    event_id = _next_event_id(db, session_id)
    row = WsEvent(
        session_id=session_id,
        task_id=task_id,
        event_id=event_id,
        event=event,
        payload=payload,
        ts=datetime.now(UTC),
    )
    try:
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "Agent WS 事件写入失败 session=%s event=%s type=%s",
            session_id,
            event,
            type(exc).__name__,
        )
        return False
    state.cursor = max(state.cursor, event_id)
    frame = _frame(session_id, event, event_id, payload, task_id=task_id, ts=row.ts)
    # 持久化事件需要让 team 会话的在线协作者即时看到；无登记连接时保底发给当前连接。
    if await SESSION_CONNECTION_HUB.broadcast_event(session_id, frame):
        return True
    return await _send(websocket, state, frame)


async def _emit_error(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    error: AppError,
) -> None:
    """将业务错误收敛为脱敏 error 事件。"""
    await _emit_persistent(
        db,
        websocket,
        state,
        session_id,
        "error",
        {"code": error.code.value, "message": error.message},
    )


def _author_payload(user: User) -> dict[str, Any]:
    """构造消息作者的非敏感展示字段。"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


def _message_payload(row: Message, user: User) -> dict[str, Any]:
    """构造与 REST 历史回放一致的 user_message 事件 payload。"""
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "attachments": row.attachments or [],
        "author_id": row.author_id,
        "author": _author_payload(user) if row.author_id else None,
        "client_message_id": row.client_message_id,
        "created_at": _iso(row.created_at),
    }


def _assistant_message_payload(row: Message) -> dict[str, Any]:
    """构造助手最终交付事件；正文与用户消息回显使用不同事件类型。"""
    return {
        "id": row.id,
        "role": "assistant",
        "text": row.content,
        "reply_latency_ms": row.latency_ms,
        "model_name": row.model_name,
        "profile_id": row.profile_id,
        "profile_name": row.profile_name,
        "provider": row.provider,
        "created_at": _iso(row.created_at),
    }


def _heartbeat_interval(db: Session) -> int:
    """读取运行时心跳秒数；配置缺失或异常时回退 15 秒。"""
    row = db.query(Setting).filter(Setting.key == "runtime").first()
    value = row.value if row else {}
    seconds = value.get("ws_ping_s", 15) if isinstance(value, dict) else 15
    return seconds if isinstance(seconds, int) and 5 <= seconds <= 300 else 15


async def _heartbeat_loop(
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    interval: int,
    stop: asyncio.Event,
) -> None:
    """在接收循环之外发送应用层 pong，保证长连接可判活。"""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            await _send(
                websocket,
                state,
                _frame(session_id, "pong", state.cursor, {}),
            )


async def _replay_events(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    last_event_id: int,
) -> None:
    """按 last_event_id 补发持久化事件，不重放瞬态流增量。"""
    rows = (
        db.query(WsEvent)
        .filter(WsEvent.session_id == session_id, WsEvent.event_id > last_event_id)
        .order_by(WsEvent.event_id)
        .all()
    )
    for row in rows:
        state.cursor = max(state.cursor, row.event_id)
        if not await _send(
            websocket,
            state,
            _frame(
                session_id,
                row.event,
                row.event_id,
                row.payload or {},
                task_id=row.task_id,
                ts=row.ts,
            ),
        ):
            return


def _selected_model_config(db: Session) -> tuple[ModelConfig, ProtocolProfile]:
    """从 Agent 设置与协议档构造模型调用配置与协议档实体，禁止使用隐式旧客户端。"""
    setting = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = setting.value if setting else None
    if not isinstance(profile_id, str) or not profile_id:
        raise AppError(ErrorCode.VALIDATION, "尚未配置 Agent 协议档")
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在")
    if "agent" not in (profile.usages or []):
        raise AppError(ErrorCode.VALIDATION, "协议档未启用 agent 用途")
    base_url, model, api_key = _profile_connection(profile, allow_global_alias=True)
    if not base_url or not model:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档配置不完整")
    reasoning_row = db.query(Setting).filter(Setting.key == "agent_reasoning").first()
    reasoning = reasoning_row.value if reasoning_row else {}
    if not isinstance(reasoning, dict):
        reasoning = {}
    reasoning_enabled = reasoning.get("enabled", True)
    reasoning_effort = reasoning.get("effort", "medium")
    if not isinstance(reasoning_enabled, bool):
        reasoning_enabled = True
    if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
        reasoning_effort = "medium"
    config = ModelConfig(
        protocol=profile.protocol,
        base_url=base_url,
        model=model,
        api_key=api_key or "",
        anthropic_version=profile.anthropic_version,
        temperature=0.2,
        max_tokens=1024,
        timeout_s=30.0,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
    )
    return config, profile


def _history_messages(db: Session, session_id: str) -> list[dict[str, str]]:
    """读取最近 20 条用户/助手消息，转换为模型层稳定消息格式。"""
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.role.in_(("user", "assistant")))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(20)
        .all()
    )
    return [
        {"role": row.role, "content": row.content}
        for row in reversed(rows)
    ]


async def _run_turn(
    session_id: str,
    websocket: WebSocket,
    state: _ConnectionState,
    abort: asyncio.Event,
) -> None:
    """后台执行一轮 LangGraph Agent，并把模型流投影为 WS 事件。"""
    db = SessionLocal()
    started = time.perf_counter()
    try:
        config, profile = _selected_model_config(db)
        request = ModelRequest.from_messages(
            config,
            _history_messages(db, session_id),
            should_abort=abort.is_set,
        )
        thinking: list[str] = []
        response: ModelResponse | None = None
        async for event in _AGENT.astream(request):
            if event.kind == "content" and event.text:
                await SESSION_CONNECTION_HUB.broadcast_chunk(
                    session_id,
                    lambda cursor, text=event.text: _frame(
                        session_id,
                        "assistant_delta",
                        cursor,
                        {"role": "assistant", "text": text},
                    ),
                )
            elif event.kind == "reasoning" and event.text:
                thinking.append(event.text)
                await _send(
                    websocket,
                    state,
                    _frame(
                        session_id,
                        "thought",
                        state.cursor,
                        {"text": event.text, "stream": "think"},
                    ),
                )
            elif event.kind == "completed":
                response = event.response

        if response is None:
            raise AppError(ErrorCode.INTERNAL, "Agent 未产生有效响应")
        latency_ms = round((time.perf_counter() - started) * 1000)

        if thinking:
            await _emit_persistent(
                db,
                websocket,
                state,
                session_id,
                "thought",
                {"text": "".join(thinking), "stream": "think_final"},
            )

        assistant = Message(
            session_id=session_id,
            role="assistant",
            content=response.text,
            attachments=[],
            author_id=None,
            client_message_id=None,
            latency_ms=latency_ms,
            model_name=profile.model or profile.name if profile else None,
            profile_id=profile.id if profile else None,
            profile_name=profile.name if profile else None,
            provider=profile.provider or profile.protocol if profile else None,
            source_id="pending",
            source_version=1,
        )
        db.add(assistant)
        db.flush()
        assistant.source_id = f"message:{assistant.id}"
        db.commit()
        await _emit_persistent(
            db,
            websocket,
            state,
            session_id,
            "assistant_message",
            _assistant_message_payload(assistant),
        )
        await _emit_persistent(
            db,
            websocket,
            state,
            session_id,
            "response.completed",
            {"finish_reason": "stop", "role": "assistant"},
        )
    except StreamAborted:
        db.rollback()
        logger.info("Agent 回合已中止 session=%s", session_id)
        await _emit_persistent(
            db,
            websocket,
            state,
            session_id,
            "response.completed",
            {"finish_reason": "cancelled", "role": "assistant"},
        )
    except AppError as exc:
        db.rollback()
        logger.info("Agent 回合失败 session=%s code=%s", session_id, exc.code.value)
        await _emit_error(db, websocket, state, session_id, exc)
        await _emit_persistent(
            db,
            websocket,
            state,
            session_id,
            "response.completed",
            {"finish_reason": "error", "role": "assistant"},
        )
    except Exception as exc:
        db.rollback()
        logger.error("Agent 回合内部异常 session=%s type=%s", session_id, type(exc).__name__)
        await _emit_error(
            db,
            websocket,
            state,
            session_id,
            AppError(ErrorCode.INTERNAL, "Agent 调用失败"),
        )
        await _emit_persistent(
            db,
            websocket,
            state,
            session_id,
            "response.completed",
            {"finish_reason": "error", "role": "assistant"},
        )
    finally:
        db.close()


async def _handle_user_message(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session: AgentSession,
    user: User,
    payload: Any,
    active_turn: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    """校验并保存用户消息，然后仅创建后台 Agent 任务。"""
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.VALIDATION, "user_message payload 必须是对象")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AppError(ErrorCode.VALIDATION, "消息内容不能为空")
    if active_turn and not active_turn.done():
        raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")

    attachments = payload.get("attachments", [])
    if not isinstance(attachments, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("file_id"), str)
        for item in attachments
    ):
        raise AppError(ErrorCode.VALIDATION, "attachments 格式不正确")
    client_message_id = payload.get("client_message_id")
    if client_message_id is not None and (
        not isinstance(client_message_id, str) or not client_message_id or len(client_message_id) > 128
    ):
        raise AppError(ErrorCode.VALIDATION, "client_message_id 格式不正确")
    if client_message_id:
        duplicate = (
            db.query(Message)
            .filter(
                Message.session_id == session.id,
                Message.client_message_id == client_message_id,
            )
            .first()
        )
        if duplicate:
            return None

    row = Message(
        session_id=session.id,
        role="user",
        content=text.strip(),
        attachments=attachments,
        author_id=user.id,
        client_message_id=client_message_id,
        source_id="pending",
        source_version=1,
    )
    db.add(row)
    db.flush()
    row.source_id = f"message:{row.id}"
    db.commit()
    await _emit_persistent(
        db,
        websocket,
        state,
        session.id,
        "user_message",
        _message_payload(row, user),
    )
    abort = asyncio.Event()
    task = asyncio.create_task(
        _run_turn(session.id, websocket, state, abort),
        name=f"agent-turn-{session.id}",
    )
    return task


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket) -> None:
    """建立短票认证的 WS 会话，并保持 receive 循环不等待模型整轮完成。"""
    db = SessionLocal()
    user: User | None = None
    session: AgentSession | None = None
    state = _ConnectionState()
    connection_id = uuid4().hex
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    active_turn: asyncio.Task[None] | None = None
    try:
        try:
            user = _consume_ws_ticket(db, websocket.query_params.get("ticket"))
            session_id = websocket.query_params.get("session_id")
            if session_id:
                session = require_visible_session(db, session_id, user.id)
            else:
                session = AgentSession(user_id=user.id, title="新会话", visibility="private")
                db.add(session)
                db.commit()
                db.refresh(session)
            raw_last_event_id = websocket.query_params.get("last_event_id", "0")
            last_event_id = max(0, int(raw_last_event_id))
        except AppError as exc:
            close_code = 4404 if exc.code == ErrorCode.NOT_FOUND else 4401
            await websocket.close(code=close_code, reason="会话不存在" if close_code == 4404 else "WebSocket 短票无效")
            return
        except ValueError:
            await websocket.close(code=4401, reason="WebSocket 连接参数无效")
            return
        except Exception as exc:
            db.rollback()
            logger.error("Agent WS 建连失败 type=%s", type(exc).__name__)
            await websocket.close(code=4401, reason="WebSocket 鉴权失败")
            return

        await websocket.accept()
        SESSION_CONNECTION_HUB.register(
            connection_id,
            session.id,
            user.id,
            websocket,
            state,
        )
        await _send(
            websocket,
            state,
            _frame(session.id, "pong", state.cursor, {}),
        )
        await _replay_events(db, websocket, state, session.id, last_event_id)
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(
                websocket,
                state,
                session.id,
                _heartbeat_interval(db),
                heartbeat_stop,
            ),
            name=f"agent-heartbeat-{session.id}",
        )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _emit_error(
                    db,
                    websocket,
                    state,
                    session.id,
                    AppError(ErrorCode.VALIDATION, "WebSocket 消息不是有效 JSON"),
                )
                continue
            if not isinstance(message, dict):
                await _emit_error(
                    db,
                    websocket,
                    state,
                    session.id,
                    AppError(ErrorCode.VALIDATION, "WebSocket 消息必须是对象"),
                )
                continue

            event = message.get("event")
            try:
                if event == "user_message":
                    active_turn = await _handle_user_message(
                        db,
                        websocket,
                        state,
                        session,
                        user,
                        message.get("payload"),
                        active_turn,
                    )
                elif event == "confirm_ack" or event == "cancel_task":
                    raise AppError(ErrorCode.VALIDATION, "当前 LangGraph Agent 尚未启用任务控制")
                else:
                    raise AppError(ErrorCode.VALIDATION, "不支持的 WebSocket 事件")
            except AppError as exc:
                await _emit_error(db, websocket, state, session.id, exc)
    except WebSocketDisconnect:
        logger.info("Agent WS 断开 session=%s", session.id if session else "unknown")
    finally:
        heartbeat_stop.set()
        if heartbeat_task:
            heartbeat_task.cancel()
        if session:
            SESSION_CONNECTION_HUB.unregister(session.id, connection_id)
        db.close()
