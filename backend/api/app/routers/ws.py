"""基于 LangGraph Agent 的 WebSocket 单轮对话入口（骨架版）。

本路由负责短票鉴权、会话事件持久化和流式传输；Agent 图仅做纯对话流式生成，
不再包含范式路由、ReAct 思考链、短工具、确认卡与澄清卡（骨架化改造）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters import StreamAborted
from ..agent import LangGraphAgent
from ..agent.attachments import model_content_for_message, normalize_attachment_refs
from ..agent.graph import iter_pending_events, router_audit_from_update
from ..agent.log import agent_trace
from ..agent.title import generate_title_text
from ..agent_prompt_settings import get_agent_prompt_overlay
from ..db import SessionLocal
from ..errors import AppError, ErrorCode
from ..harness.context import recent_window, skill_hint_lines
from ..harness.execution.context import ToolExecutionContext
from ..harness.execution.task_tools import cancel_task_safe
from ..harness.memory import get_default_checkpointer, to_serializable_request
from ..harness.prompts import SystemVars, build_system_prompt
from ..llm import ModelConfig, ModelRequest
from ..models import Message, ProtocolProfile, Setting, User, WsEvent
from ..models import Session as AgentSession
from ..security import TOKEN_TYPE_WS, decode_token
from ..session_access import require_visible_session
from ..session_connections import SESSION_CONNECTION_HUB
from ..ws_tickets import consume_ws_jti, ttl_from_jwt_payload
from .profiles import _profile_connection

router = APIRouter(tags=["ws"])
logger = logging.getLogger("ai-eval.agent-ws")

# 生产 Agent 图：挂载默认 Checkpointer（阶段 3，M3-D4）。
# 当前为 InMemoryCheckpointer（单副本进程内 dict + 容量上限），PG 引擎
# （PgCheckpointer）接入后由 get_default_checkpointer() 无感切换；
# 每回合独立 thread_id 隔离回合，检查点不跨回合复用。
_AGENT = LangGraphAgent(
    checkpointer=get_default_checkpointer(),
)
_TICKET_LOCK = threading.Lock()
# 会话级 abort 事件注册表（/stop 即时中断；单副本进程内 dict，见 AGENTS.md）
_SESSION_ABORTS: dict[str, asyncio.Event] = {}
# 标题生成中去重：同一会话一次只跑一个 AI 标题任务，避免并发消息重复调模型
_TITLE_GENERATING: set[str] = set()


class _ConnectionState:
    """单个 WebSocket 连接的发送锁与事件游标。"""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.cursor = 0


@dataclass
class _TurnHandle:
    """会话级 Agent 回合租约，隔离多连接并发与旧任务清理。"""

    turn_id: str
    user_id: str
    abort: asyncio.Event
    task: asyncio.Task[None] | None = None
    started: bool = False
    terminal_emitted: bool = False


# 一个共享会话同一时刻只能有一个交互回合；锁只保护本进程内短临界区，不跨越 await。
_TURN_LOCK = threading.Lock()
_SESSION_TURNS: dict[str, _TurnHandle] = {}


def _turn_busy(session_id: str, local_task: asyncio.Task[None] | None = None) -> bool:
    """判断会话是否已有尚未完成的回合，覆盖同会话多条 WebSocket 连接。"""
    if local_task is not None and not local_task.done():
        return True
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        return current is not None and (current.task is None or not current.task.done())


def _reserve_turn(
    session_id: str,
    user_id: str,
    *,
    local_task: asyncio.Task[None] | None = None,
) -> _TurnHandle:
    """原子抢占会话回合；失败时不写入用户消息或恢复令牌。"""
    if local_task is not None and not local_task.done():
        raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is not None and (current.task is None or not current.task.done()):
            raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")
        handle = _TurnHandle(
            turn_id=f"{session_id}:{uuid4().hex}",
            user_id=str(user_id),
            abort=asyncio.Event(),
        )
        _SESSION_TURNS[session_id] = handle
        _SESSION_ABORTS[session_id] = handle.abort
        return handle


def _release_turn(handle: _TurnHandle, task: asyncio.Task[None] | None = None) -> None:
    """只清理仍指向当前租约的映射，防止旧任务回调误删新回合 abort。"""
    session_id = handle.turn_id.split(":", 1)[0]
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is not handle:
            return
        if task is not None and current.task is not task:
            return
        _SESSION_TURNS.pop(session_id, None)
        if _SESSION_ABORTS.get(session_id) is handle.abort:
            _SESSION_ABORTS.pop(session_id, None)


def _attach_turn_task(handle: _TurnHandle, task: asyncio.Task[None]) -> None:
    """把后台任务绑定到租约，并用身份校验注册完成回调。"""
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(handle.turn_id.split(":", 1)[0])
        if current is not handle:
            task.cancel()
            raise AppError(ErrorCode.CONCURRENCY, "Agent 回合已失效，请重试")
        handle.task = task
    # stop 可能在 task 首次调度前到达；先让它启动并由 abort 路径发出唯一 completed。
    if handle.abort.is_set() and handle.started:
        task.cancel()
    task.add_done_callback(lambda done: _release_turn(handle, done))


def _claim_terminal(session_id: str, turn_id: str | None) -> bool:
    """为回合抢占唯一完成事件；旧任务或 stop 不得重复发送 completed。"""
    if not turn_id:
        return True
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is None or current.turn_id != turn_id or current.terminal_emitted:
            return False
        current.terminal_emitted = True
        return True


def _turn_owner(session_id: str) -> str | None:
    """读取当前回合所有者，仅返回非敏感用户 ID。"""
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        return current.user_id if current else None


def _start_turn(
    session_id: str,
    websocket: WebSocket,
    state: _ConnectionState,
    user_id: str,
    *,
    handle: _TurnHandle,
) -> asyncio.Task[None]:
    """创建并登记后台 Harness 回合；收包循环永不等待整轮图执行。"""
    task = asyncio.create_task(
        _run_turn(
            session_id,
            websocket,
            state,
            handle.abort,
            user_id=user_id,
            turn_id=handle.turn_id,
        ),
        name=f"agent-turn-{session_id}",
    )
    try:
        _attach_turn_task(handle, task)
    except Exception:
        task.cancel()
        raise
    return task


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


async def _send_unlocked(websocket: WebSocket, frame: dict[str, Any]) -> bool:
    """在调用方已持有连接锁时发送一帧，统一吞掉底层连接异常。"""
    try:
        await websocket.send_json(frame)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False
    except Exception as exc:
        logger.info("Agent WS 发送失败 type=%s", type(exc).__name__)
        return False


async def _send(
    websocket: WebSocket,
    state: _ConnectionState,
    frame: dict[str, Any],
) -> bool:
    """串行发送一帧；连接已关闭时只返回失败，不把底层异常泄露给前端。"""
    async with state.lock:
        return await _send_unlocked(websocket, frame)


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
    ttl_seconds = ttl_from_jwt_payload(payload)
    with _TICKET_LOCK:
        first_use = consume_ws_jti(jti, ttl_seconds)
    if not first_use:
        raise AppError(ErrorCode.UNAUTHORIZED, "WebSocket 短票已使用", status_code=401)

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or user.disabled or payload.get("av") != user.auth_version:
        raise AppError(ErrorCode.UNAUTHORIZED, "用户不可用", status_code=401)
    return user


def _next_event_id(db: Session, session_id: str) -> int:
    """计算会话内下一个单调事件号；先锁会话行，避免与 Worker 撞号。"""
    locked = (
        db.query(AgentSession.id)
        .filter(AgentSession.id == session_id)
        .with_for_update()
        .first()
    )
    if not locked:
        return 1
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
    row: WsEvent | None = None
    event_id = 0
    for attempt in range(2):
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
            break
        except IntegrityError:
            db.rollback()
            if attempt == 0:
                continue
            logger.error(
                "Agent WS 事件号冲突 session=%s event=%s",
                session_id,
                event,
            )
            return False
        except Exception as exc:
            db.rollback()
            logger.error(
                "Agent WS 事件写入失败 session=%s event=%s type=%s",
                session_id,
                event,
                type(exc).__name__,
            )
            return False
    else:
        return False
    if row is None:
        return False
    frame = _frame(session_id, event, event_id, payload, task_id=task_id, ts=row.ts)
    # 持久化事件需要让 team 会话的在线协作者即时看到；无登记连接时保底发给当前连接。
    # 不要提前推进当前连接游标：Hub 需要据此判断回放期间的排队事件是否已补发。
    if await SESSION_CONNECTION_HUB.broadcast_event(session_id, frame):
        return True
    state.cursor = max(state.cursor, event_id)
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
        "turn_stats": row.turn_stats,
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


# Worker 进程外写入的事件轮询间隔（秒）；过短打库，过长进度卡顿。
_FORWARD_POLL_S = 0.4
# Worker 直产事件（M6-D5 / M9-D8）；图节点事件已由 _emit_persistent 即时广播。
_WORKER_FORWARD_EVENTS = frozenset({"progress", "report", "error"})


def _should_forward_worker_event(event: str, task_id: str | None) -> bool:
    """判断一条 ws_events 是否应由转发循环推给在线连接。

    ``error`` 无 ``task_id`` 多为对话内 Agent 错误，已由 ``_emit_persistent``
    发出；带 ``task_id`` 的才是 Worker 任务失败。
    """
    if event in {"progress", "report"}:
        return True
    return event == "error" and bool(task_id)


async def _forward_loop(
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    stop: asyncio.Event,
) -> None:
    """按游标增量把 Worker 写入的 ws_events 推到当前连接（M9-D8）。

    查询 / 发送 / 游标推进在同一把连接锁内，避免与 ``_emit_persistent``
    并发重复推送。使用独立 Session，不占用收包循环的 ``db``。
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_FORWARD_POLL_S)
            return
        except TimeoutError:
            pass
        db = SessionLocal()
        try:
            async with state.lock:
                rows = (
                    db.query(WsEvent)
                    .filter(
                        WsEvent.session_id == session_id,
                        WsEvent.event_id > state.cursor,
                        WsEvent.event.in_(_WORKER_FORWARD_EVENTS),
                    )
                    .order_by(WsEvent.event_id)
                    .all()
                )
                for row in rows:
                    if not _should_forward_worker_event(row.event, row.task_id):
                        # 已由本连接 _emit 发出的对话错误：只推进游标，避免每轮重扫。
                        state.cursor = max(state.cursor, row.event_id)
                        continue
                    frame = _frame(
                        session_id,
                        row.event,
                        row.event_id,
                        row.payload or {},
                        task_id=row.task_id,
                        ts=row.ts,
                    )
                    try:
                        await websocket.send_json(frame)
                        state.cursor = max(state.cursor, row.event_id)
                    except (WebSocketDisconnect, RuntimeError):
                        return
                    except Exception as exc:
                        logger.info(
                            "Agent WS 转发发送失败 type=%s",
                            type(exc).__name__,
                        )
                        return
        except Exception as exc:
            logger.info("Agent WS 转发查询失败 type=%s", type(exc).__name__)
        finally:
            db.close()


async def _replay_events(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    last_event_id: int,
) -> None:
    """按 last_event_id 补发持久化事件，并先推进游标避免 Worker 旧事件重发。"""
    # 即使没有待补发事件，也必须承接客户端游标；否则 forward_loop 会从 0 重扫。
    state.cursor = max(state.cursor, last_event_id)
    rows = (
        db.query(WsEvent)
        .filter(WsEvent.session_id == session_id, WsEvent.event_id > last_event_id)
        .order_by(WsEvent.event_id)
        .all()
    )
    # 回放与当前连接的广播共用同一把锁；Hub 会在锁外登记/排队新事件。
    async with state.lock:
        for row in rows:
            if row.event_id <= state.cursor:
                continue
            frame = _frame(
                session_id,
                row.event,
                row.event_id,
                row.payload or {},
                task_id=row.task_id,
                ts=row.ts,
            )
            if not await _send_unlocked(websocket, frame):
                return
            state.cursor = row.event_id


DEFAULT_AGENT_SYSTEM = (
    "你是 AI 测试与评估平台的智能助手。保持客观、精炼、专业，使用中文进行逻辑思考与交流。"
    "在思考问题时，请使用中文分步骤分析用户输入与目标，并给出清晰、专业的中文回复。"
    "你的职责是协助研发与评测团队完成大模型基准评测、知识库评估、测试用例生成与压测等任务。"
)


@dataclass(frozen=True)
class _ProfileSnapshot:
    """协议档纯数据快照：仅含回合所需的已加载标量字段，缓存安全。

    修复根因：缓存曾直接保存 detach 后的 ProtocolProfile ORM 实例；写入缓存
    的回合随后 commit（expire_on_commit 使属性过期）并关闭 Session（实例
    detach），命中缓存的回合访问属性时抛 DetachedInstanceError，被兜底为
    INTERNAL「Agent 调用失败」。快照不再绑定任何 ORM 会话。
    """

    id: str
    name: str
    model: str
    base_url: str
    protocol: str


# 协议档配置快照缓存：Agent 每回合读取，TTL 内复用（省 profile+reasoning 两次
# 查询与环境文件解析）；管理端改档/改 Key 最迟 TTL 秒后生效。缓存只存纯数据
# 快照（_ProfileSnapshot + ModelConfig），禁止缓存 ORM 实例（detach/expire
# 后访问属性会抛 DetachedInstanceError）。
_MODEL_CONFIG_CACHE: dict[str, tuple[float, tuple[ModelConfig, _ProfileSnapshot]]] = {}
_MODEL_CONFIG_CACHE_TTL_S = 15.0


def _selected_model_config(db: Session) -> tuple[ModelConfig, _ProfileSnapshot]:
    """从 Agent 设置与协议档构造模型调用配置与协议档快照，禁止使用隐式旧客户端。"""
    setting = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = setting.value if setting else None
    if not isinstance(profile_id, str) or not profile_id:
        raise AppError(ErrorCode.VALIDATION, "尚未配置 Agent 协议档")
    cached = _MODEL_CONFIG_CACHE.get(profile_id)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]
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
        # 输出上限从协议档 max_output_tokens 读取（默认 8192）：长文档总结/
        # 导出类任务可调大，避免回答在输出上限处被上游截断。
        max_tokens=int(getattr(profile, "max_output_tokens", 0) or 8192),
        timeout_s=60.0,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        tool_call_mode=getattr(profile, "tool_call_mode", "native") or "native",
    )
    snapshot = _ProfileSnapshot(
        id=profile.id,
        name=profile.name,
        model=profile.model,
        base_url=profile.base_url,
        protocol=profile.protocol,
    )
    _MODEL_CONFIG_CACHE[profile_id] = (now + _MODEL_CONFIG_CACHE_TTL_S, (config, snapshot))
    return config, snapshot


def _window_messages(db: Session, session_id: str) -> list[dict]:
    """读取会话消息，经 Harness 窗口算法（CX-1）投影（含 source_id）。

    ``compact_keep_from`` 指定保留起点时截断更早消息；思考/工具/确认/进度
    事件不进窗口（CX-2）。窗口算法唯一来源为
    ``app.harness.context.window.recent_window``。
    """
    session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
    keep_from = session.compact_keep_from if session else None
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.role.in_(("user", "assistant")))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(200)
        .all()
    )
    ordered = [
        {
            "role": row.role,
            "content": model_content_for_message(db, row) if row.role == "user" else row.content,
            "source_id": row.source_id,
        }
        for row in reversed(rows)
    ]
    return recent_window(ordered, limit=20, keep_from=keep_from)


def _history_messages(db: Session, session_id: str) -> list[dict[str, str]]:
    """模型层稳定消息格式（窗口投影，去掉 source_id）。"""
    return [
        {"role": item["role"], "content": item["content"]}
        for item in _window_messages(db, session_id)
    ]


def _infer_provider(profile: _ProfileSnapshot | None) -> str | None:
    """根据协议档的模型名、名称、URL 与协议类型推断供应商标识，供前端精准呈现 ProviderLogo。"""
    if profile is None:
        return None
    model = (profile.model or "").lower()
    name = (profile.name or "").lower()
    url = (profile.base_url or "").lower()

    # 1. 优先匹配模型名归属（支持托管在聚合平台的特定模型）
    if "stepfun" in model or "step-" in model or "stepfun" in name or "阶跃" in name or "stepfun" in url:
        return "stepfun"
    if "deepseek" in model or "deepseek" in name or "deepseek" in url:
        return "deepseek"
    if "qwen" in model or "tongyi" in name or "aliyun" in url or "dashscope" in url:
        return "qwen"
    if model.startswith("claude-") or "claude" in model or "anthropic" in name or "anthropic" in url or profile.protocol == "anthropic_messages":
        return "anthropic"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-")) or "openai" in name or "openai" in url:
        return "openai"
    if model.startswith("gemini-") or "gemini" in model or "google" in url or "generativelanguage" in url:
        return "gemini"
    if "glm" in model or "zhipu" in name or "智谱" in name or "bigmodel.cn" in url:
        return "zhipu"
    if "kimi" in model or "moonshot" in model or "kimi" in name or "月之暗面" in name or "moonshot" in url:
        return "moonshot"
    if "mistral" in model or "mistral" in name or "mistral" in url:
        return "mistral"
    if "doubao" in model or "火山" in name or "豆包" in name or "volces.com" in url:
        return "volcengine"
    if "ernie" in model or "qianfan" in name or "文心" in name or "千帆" in name or "qianfan" in url or "baidubce" in url:
        return "qianfan"
    if "hunyuan" in model or "混元" in name or "tencent" in url:
        return "hunyuan"

    # 2. 匹配托管服务与端点平台
    if "nvidia" in url or "nvidia" in name or "nvidia" in model:
        return "nvidia"
    if "xiaomimimo" in url or "mimo" in name or "mimo" in model:
        return "mimo"
    if "siliconflow" in url or "silicon" in name or "硅基" in name:
        return "siliconflow"
    if "groq" in url or "groq" in name:
        return "groq"
    if "11434" in url or "ollama" in url or "ollama" in name:
        return "ollama"
    if "together" in url or "together" in name:
        return "together"
    return "custom"


async def _emit_turn_completed(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    *,
    finish_reason: str,
    turn_id: str | None,
    router_audit: dict | None = None,
) -> None:
    """以回合租约保证 response.completed 至多落库并发送一次。

    ``router_audit`` 为 Router 审计三元组（H1）：取消 / 异常收尾时若 Router
    已执行则随 completed 落库，保证 O2 判错信号（如 agent 分支立即 /stop）
    可从 ws_events 推导；主开关关闭时恒为 None，payload 与历史完全一致。
    """
    if not _claim_terminal(session_id, turn_id):
        return
    payload: dict[str, object] = {"finish_reason": finish_reason, "role": "assistant"}
    if router_audit:
        payload.update(router_audit)
    await _emit_persistent(
        db,
        websocket,
        state,
        session_id,
        "response.completed",
        payload,
    )


async def _translate_event(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    profile: _ProfileSnapshot | None,
    event: dict,
    *,
    turn_id: str | None = None,
) -> None:
    """把图节点产出的 NodeEvent 翻译为 ws event（落库 + 统一 emit）。

    事件桥接契约（§2.5）：节点只返回纯数据，持久化事件全部经本函数落
    ``ws_events`` 并广播；``assistant_message`` 需先落库 Message 再构造对外
    payload（对齐 REST 历史回放格式）。
    """
    kind = event["kind"]
    payload = event.get("payload") or {}
    task_id = event.get("task_id")
    if kind == "response.completed" and not _claim_terminal(session_id, turn_id):
        return
    if kind == "assistant_message":
        assistant = Message(
            session_id=session_id,
            role="assistant",
            content=str(payload.get("text") or ""),
            attachments=[],
            author_id=None,
            client_message_id=None,
            latency_ms=int(payload.get("latency_ms") or 0),
            turn_stats=payload.get("turn_stats") or None,
            model_name=profile.model or profile.name if profile else None,
            profile_id=profile.id if profile else None,
            profile_name=profile.name if profile else None,
            provider=_infer_provider(profile),
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
            task_id=task_id,
        )
        return
    if kind == "error":
        await _emit_persistent(
            db,
            websocket,
            state,
            session_id,
            "error",
            {
                "code": str(payload.get("code") or "validation"),
                "message": str(payload.get("message") or "操作失败"),
            },
            task_id=task_id,
        )
        return
    await _emit_persistent(
        db,
        websocket,
        state,
        session_id,
        kind,
        dict(payload),
        task_id=task_id,
    )


async def _run_turn(
    session_id: str,
    websocket: WebSocket,
    state: _ConnectionState,
    abort: asyncio.Event,
    *,
    user_id: str,
    turn_id: str | None = None,
) -> None:
    """后台执行一轮 LangGraph Agent，并把图输出统一投影为 WS 事件。

    图节点只返回纯数据（custom 瞬态帧 + pending_events 事件意图）；本函数
    消费 ``astream`` 输出后统一 emit（§2.5 事件桥接）。``should_abort`` 与
    api_key 经 ``RunnableConfig.configurable`` 注入（O-12 迁移），不入 State。
    骨架版仅纯对话流式生成，不处理 interrupt / 思考链 / 工具帧。
    """
    if turn_id:
        with _TURN_LOCK:
            current = _SESSION_TURNS.get(session_id)
            if current is not None and current.turn_id == turn_id:
                current.started = True
    db = SessionLocal()
    # Router 审计三元组（H1）：先置空再进 try，任何阶段异常收尾均可安全携带
    router_audit: dict | None = None
    try:
        config, profile = _selected_model_config(db)
        history = _history_messages(db, session_id)
        # 核心系统策略始终由 Harness 生成；协议档只能注入受审计的补充提示词。
        system_prompt = build_system_prompt(
            SystemVars(
                skill_hints=tuple(skill_hint_lines()),
                agent_prompt_overlay=get_agent_prompt_overlay(db, profile.id),
            )
        )
        session_row = db.query(AgentSession).filter(AgentSession.id == session_id).first()
        compact_summary = (session_row.compact_summary or "") if session_row else ""
        serializable = to_serializable_request(
            ModelRequest.from_messages(config, history, system=system_prompt)
        )
        # 新回合复用租约 ID 作为检查点线程 ID，便于并发与中断审计关联。
        thread_id = turn_id or f"{session_id}:{uuid4().hex}"
        graph_config = {
            "configurable": {
                # 每回合独立 thread_id：检查点按回合隔离（M3 阶段 3）
                "thread_id": thread_id,
                "abort": {"should_abort": abort.is_set},
                "credentials": {
                    "api_key": config.api_key or "",
                    "user_id": user_id,
                },
                "session": {
                    "id": session_id,
                    # compact 摘要供 M2 assemble 注入【会话摘要】，不入 GraphState
                    "compact_summary": compact_summary,
                },
                # 协议档 ID 用于助手消息头快照，不含密钥。
                "profile": {"id": profile.id},
            }
        }
        deferred_completed: list[dict] = []

        async for mode, chunk in _AGENT.astream(serializable, config=graph_config):
            if mode == "custom":
                kind = str(chunk.get("kind") or "")
                text = str(chunk.get("text") or "")
                if kind == "content" and text:
                    await SESSION_CONNECTION_HUB.broadcast_chunk(
                        session_id,
                        lambda cursor, text=text: _frame(
                            session_id,
                            "assistant_delta",
                            cursor,
                            {"role": "assistant", "text": text},
                        ),
                    )
                continue
            # updates 模式：按节点边界消费 pending_events，统一 emit；
            # Router 节点一旦执行即捕获审计三元组，供取消/异常收尾携带（O2）
            router_audit = router_audit_from_update(chunk) or router_audit
            for event in iter_pending_events(chunk):
                if event.get("kind") == "response.completed":
                    # completed 必须是本轮最后一条持久事件。
                    deferred_completed.append(event)
                    continue
                await _translate_event(
                    db,
                    websocket,
                    state,
                    session_id,
                    profile,
                    event,
                    turn_id=turn_id,
                )
        for event in deferred_completed:
            await _translate_event(
                db,
                websocket,
                state,
                session_id,
                profile,
                event,
                turn_id=turn_id,
            )
    except asyncio.CancelledError:
        db.rollback()
        if abort.is_set():
            logger.info("Agent 回合已中止 session=%s", session_id)
            await _emit_turn_completed(
                db,
                websocket,
                state,
                session_id,
                finish_reason="cancelled",
                turn_id=turn_id,
                router_audit=router_audit,
            )
            return
        raise
    except StreamAborted:
        db.rollback()
        logger.info("Agent 回合已中止 session=%s", session_id)
        await _emit_turn_completed(
            db,
            websocket,
            state,
            session_id,
            finish_reason="cancelled",
            turn_id=turn_id,
            router_audit=router_audit,
        )
    except AppError as exc:
        db.rollback()
        logger.info("Agent 回合失败 session=%s code=%s", session_id, exc.code.value)
        await _emit_error(db, websocket, state, session_id, exc)
        await _emit_turn_completed(
            db,
            websocket,
            state,
            session_id,
            finish_reason="error",
            turn_id=turn_id,
            router_audit=router_audit,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Agent 回合内部异常 session=%s type=%s", session_id, type(exc).__name__)
        await _emit_error(
            db,
            websocket,
            state,
            session_id,
            AppError(ErrorCode.INTERNAL, "Agent 调用失败"),
        )
        await _emit_turn_completed(
            db,
            websocket,
            state,
            session_id,
            finish_reason="error",
            turn_id=turn_id,
            router_audit=router_audit,
        )
    finally:
        db.close()


async def _handle_stop(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    active_turn: asyncio.Task[None] | None,
    user_id: str | None = None,
) -> None:
    """/stop 中止当前 Harness 回合，并限制为本轮发起成员执行。

    骨架版无人工中断（澄清/危险工具确认），/stop 仅取消活跃图回合；活跃
    回合由后台任务统一发送唯一 ``response.completed``，避免 stop 与任务竞态重复收尾。
    """
    with _TURN_LOCK:
        turn = _SESSION_TURNS.get(session_id)
    owner = turn.user_id if turn else None
    if user_id and owner and str(user_id) != str(owner):
        raise AppError(ErrorCode.UNAUTHORIZED, "仅本轮发起成员可以执行 /stop")

    abort = turn.abort if turn else _SESSION_ABORTS.get(session_id)
    active = False
    if turn and (turn.task is None or not turn.task.done()):
        active = True
        turn.abort.set()
        if turn.task is not None and turn.started:
            turn.task.cancel()
    elif active_turn and not active_turn.done():
        active = True
        if abort:
            abort.set()
        active_turn.cancel()
    # 有活跃后台任务时不在收包循环抢发 completed，由 _run_turn 的取消分支收尾。
    if active:
        return
    await _emit_turn_completed(
        db,
        websocket,
        state,
        session_id,
        finish_reason="cancelled",
        turn_id=turn.turn_id if turn else None,
    )


def _maybe_schedule_title(
    session: AgentSession,
    websocket: WebSocket,
    state: _ConnectionState,
    text: str,
) -> None:
    """会话仍是默认标题时，首条消息后后台生成 AI 标题并广播。

    fire-and-forget：绝不 await、绝不阻塞收包循环；生成、落库、广播任何
    一步失败都只记 agent_trace，标题不是对话关键路径。
    """
    stripped = text.strip()
    if not stripped or session.title != "新会话":
        return
    if session.id in _TITLE_GENERATING:
        return
    _TITLE_GENERATING.add(session.id)

    async def _apply() -> None:
        db = SessionLocal()
        try:
            title = await generate_title_text(stripped)
            if not title:
                return
            # 行锁复查默认标题：避免与用户手动改名或并发任务互相覆盖
            row = (
                db.query(AgentSession)
                .filter(AgentSession.id == session.id)
                .with_for_update()
                .first()
            )
            if row is None or row.title != "新会话":
                return
            row.title = title
            db.commit()
            await _emit_persistent(
                db,
                websocket,
                state,
                session.id,
                "session_title",
                {"title": title, "source": "ai"},
            )
        except Exception as exc:
            db.rollback()
            agent_trace(f"session title apply failed type={type(exc).__name__}")
        finally:
            _TITLE_GENERATING.discard(session.id)
            db.close()

    asyncio.create_task(_apply(), name=f"agent-title-{session.id}")


async def _handle_user_message(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session: AgentSession,
    user: User,
    payload: Any,
    active_turn: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    """校验并保存用户消息，再原子抢占会话回合并创建后台 Agent 任务。"""
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.VALIDATION, "user_message payload 必须是对象")
    text = payload.get("text")
    if not isinstance(text, str):
        raise AppError(ErrorCode.VALIDATION, "消息内容格式不正确")

    attachments = payload.get("attachments", [])
    if not isinstance(attachments, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("file_id"), str)
        for item in attachments
    ):
        raise AppError(ErrorCode.VALIDATION, "attachments 格式不正确")
    if not text.strip() and not attachments:
        raise AppError(ErrorCode.VALIDATION, "消息内容不能为空")
    normalized_attachments = normalize_attachment_refs(db, attachments, owner_id=user.id)
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

    if _turn_busy(session.id, active_turn):
        raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")

    handle = _reserve_turn(session.id, str(user.id), local_task=active_turn)
    try:
        row = Message(
            session_id=session.id,
            role="user",
            content=text.strip(),
            attachments=normalized_attachments,
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
        # 首条消息后后台生成 AI 会话标题（默认标题才触发，见 API.md §4.3）
        _maybe_schedule_title(session, websocket, state, text)
        return _start_turn(
            session.id,
            websocket,
            state,
            str(user.id),
            handle=handle,
        )
    except Exception:
        db.rollback()
        _release_turn(handle)
        raise


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
    forward_task: asyncio.Task[None] | None = None
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
            ready=False,
        )
        state.cursor = last_event_id
        await _send(
            websocket,
            state,
            _frame(session.id, "pong", state.cursor, {}),
        )
        await _replay_events(db, websocket, state, session.id, last_event_id)
        if not await SESSION_CONNECTION_HUB.activate(session.id, connection_id):
            return
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
        # Worker 进程外写入的 progress/report/error：在线连接靠本循环实时推送。
        forward_task = asyncio.create_task(
            _forward_loop(websocket, state, session.id, heartbeat_stop),
            name=f"agent-forward-{session.id}",
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
                    payload = message.get("payload")
                    if isinstance(payload, dict):
                        text = payload.get("text")
                        if isinstance(text, str):
                            stripped = text.strip()
                            if stripped.startswith("/stop"):
                                # /stop 即时中断：不进图，直接取消当前回合（§2.5）
                                await _handle_stop(
                                    db,
                                    websocket,
                                    state,
                                    session.id,
                                    active_turn,
                                    user.id,
                                )
                                continue
                    active_turn = await _handle_user_message(
                        db,
                        websocket,
                        state,
                        session,
                        user,
                        message.get("payload"),
                        active_turn,
                    )
                elif event == "cancel_task":
                    payload = (
                        message.get("payload")
                        if isinstance(message.get("payload"), dict)
                        else {}
                    )
                    result = cancel_task_safe(
                        payload,
                        ToolExecutionContext(
                            session_id=session.id,
                            user_id=user.id,
                            thread_id=session.id,
                            call_id="ws-cancel",
                        ),
                    )
                    await _emit_persistent(
                        db,
                        websocket,
                        state,
                        session.id,
                        "task_cancelled",
                        {
                            "status": result.get("status"),
                            "kind": result.get("kind"),
                        },
                        task_id=str(result.get("task_id") or "") or None,
                    )
                else:
                    raise AppError(ErrorCode.VALIDATION, "不支持的 WebSocket 事件")
            except AppError as exc:
                await _emit_error(db, websocket, state, session.id, exc)
    except WebSocketDisconnect:
        logger.info("Agent WS 断开 session=%s", session.id if session else "unknown")
    finally:
        heartbeat_stop.set()
        cleanup_tasks = [task for task in (heartbeat_task, forward_task) if task is not None]
        for task in cleanup_tasks:
            task.cancel()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        if session:
            SESSION_CONNECTION_HUB.unregister(session.id, connection_id)
        db.close()
