"""基于 LangGraph Agent 的 WebSocket 单轮对话入口。

本路由负责短票鉴权、会话事件持久化和流式传输；Agent 图负责单轮模型调用与
短工具 ReAct，长任务仍通过任务队列交给 Worker，避免耗时执行阻塞 API 进程。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters import StreamAborted
from ..agent import LangGraphAgent
from ..agent.attachments import model_content_for_message, normalize_attachment_refs
from ..agent.graph import iter_pending_events
from ..agent.think_stream import ThinkStreamCoalescer
from ..config import settings
from ..db import SessionLocal
from ..errors import AppError, ErrorCode
from ..harness.context import recent_window, skill_hint_lines, summarize
from ..harness.execution import ensure_session_workspace
from ..harness.execution.context import ToolExecutionContext
from ..harness.execution.task_tools import cancel_task_safe
from ..harness.memory import get_default_checkpointer, to_serializable_request, write_summary
from ..harness.orchestration import drop_stale_asset_ids, handle_confirm_ack
from ..harness.orchestration.confirm_spec import build_slash_stress_spec
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
    db_factory=SessionLocal,
)
_TICKET_LOCK = threading.Lock()
# 会话级 abort 事件注册表（/stop 即时中断；单副本进程内 dict，见 AGENTS.md）
_SESSION_ABORTS: dict[str, asyncio.Event] = {}
# 会话级待回复澄清卡注册表（interrupt() 暂停后保存，clarify_reply 恢复图用）
_SESSION_CLARIFY: dict[str, dict] = {}


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


DEFAULT_AGENT_SYSTEM = (
    "你是 AI 测试与评估平台的智能助手。保持客观、精炼、专业，使用中文进行逻辑思考与交流。"
    "在思考问题时，请使用中文分步骤分析用户输入与目标，并给出清晰、专业的中文回复。"
    "你的职责是协助研发与评测团队完成大模型基准评测、知识库评估、测试用例生成与压测等任务。"
)


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
        max_tokens=8192,
        timeout_s=60.0,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        tool_call_mode=getattr(profile, "tool_call_mode", "legacy") or "legacy",
    )
    return config, profile


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


def _infer_provider(profile: ProtocolProfile | None) -> str | None:
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


def _persist_pending_confirm(db: Session, session_id: str, payload: dict[str, Any]) -> None:
    """把确认卡 TaskSpec 写入 sessions.pending_confirm，供 confirm_ack 二次校验。

    ``confirm_author`` 只作归属元数据，不进入卡标 JSON（前端提交 patch 须剥离）。
    """
    spec = dict(payload)
    author = spec.pop("confirm_author", None)
    author_id = author.get("id") if isinstance(author, dict) else None
    session = (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id)
        .with_for_update()
        .first()
    )
    if not session:
        return
    session.pending_confirm = spec
    session.pending_confirm_author_id = str(author_id) if author_id else session.user_id
    db.commit()


def _confirm_author_payload(user: User | None) -> dict[str, str] | None:
    """确认卡作者元数据；不进卡标 JSON，仅供前端展示与 pending_confirm_author_id。"""
    if user is None or not user.id:
        return None
    return {
        "id": str(user.id),
        "username": str(user.username or ""),
        "display_name": str(user.display_name or user.username or ""),
    }


async def _translate_event(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    profile: ProtocolProfile | None,
    event: dict,
    *,
    user: User | None = None,
) -> None:
    """把图节点产出的 NodeEvent 翻译为 ws event（落库 + 统一 emit）。

    事件桥接契约（§2.5）：节点只返回纯数据，持久化事件全部经本函数落
    ``ws_events`` 并广播；``assistant_message`` 需先落库 Message 再构造对外
    payload（对齐 REST 历史回放格式）。
    """
    kind = event["kind"]
    payload = event.get("payload") or {}
    task_id = event.get("task_id")
    if kind == "assistant_message":
        assistant = Message(
            session_id=session_id,
            role="assistant",
            content=str(payload.get("text") or ""),
            attachments=[],
            author_id=None,
            client_message_id=None,
            latency_ms=int(payload.get("latency_ms") or 0),
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
    if kind == "confirm":
        outgoing = dict(payload)
        author = _confirm_author_payload(user)
        if author and "confirm_author" not in outgoing:
            outgoing["confirm_author"] = author
        _persist_pending_confirm(db, session_id, outgoing)
        payload = outgoing
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
    resume: dict | None = None,
) -> None:
    """后台执行一轮 LangGraph Agent，并把图输出统一投影为 WS 事件。

    图节点只返回纯数据（custom 瞬态帧 + pending_events 事件意图）；本函数
    消费 ``astream`` 输出后统一 emit（§2.5 事件桥接）。``should_abort`` 与
    api_key 经 ``RunnableConfig.configurable`` 注入（O-12 迁移），不入 State。

    ``resume`` 非 None 时为澄清卡恢复模式：以 ``Command(resume=answer)``
    恢复同一 thread_id 的图（M9 §3.5.1），不再构造新请求。
    """
    db = SessionLocal()
    try:
        config, profile = _selected_model_config(db)
        turn_user = db.query(User).filter(User.id == user_id).first()
        history = _history_messages(db, session_id)
        # 系统提示词：agent_system_prompt 设置行优先，回退 Harness 五段策略（#101）
        system_row = db.query(Setting).filter(Setting.key == "agent_system_prompt").first()
        system_prompt = (
            system_row.value
            if (system_row and isinstance(system_row.value, str) and system_row.value.strip())
            else build_system_prompt(SystemVars(skill_hints=tuple(skill_hint_lines())))
        )
        session_row = db.query(AgentSession).filter(AgentSession.id == session_id).first()
        compact_summary = (session_row.compact_summary or "") if session_row else ""
        if resume is not None:
            # 恢复模式：复用中断时的 thread_id，不构造新请求
            serializable = None
            thread_id = str(resume["thread_id"])
            resume_answer = resume.get("answer")
        else:
            serializable = to_serializable_request(
                ModelRequest.from_messages(config, history, system=system_prompt)
            )
            thread_id = f"{session_id}:{uuid4().hex}"
            resume_answer = None
        # 会话工作区：每个会话一个独立文件夹（read/write/edit 与 bash 的
        # 沙箱根，经 configurable 注入，toolnode 优先读取此值）
        sandbox_dir = ensure_session_workspace(session_id)
        # 资产溯源：窗口内用户消息的附件 file_ids 注入 configurable，供
        # routing_node 强制 react（本轮或历史轮带附件均走 react，模型才能用
        # read 工具）与 toolnode 附件归属门禁读取
        recent_users = (
            db.query(Message)
            .filter(Message.session_id == session_id, Message.role == "user")
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(200)
            .all()
        )
        owned_file_ids: list[str] = []
        for row in recent_users:
            for item in row.attachments or []:
                if isinstance(item, dict) and isinstance(item.get("file_id"), str):
                    if item["file_id"] not in owned_file_ids:
                        owned_file_ids.append(item["file_id"])
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
                "assets": {"file_ids": owned_file_ids},
                # 沙箱引擎与资源限制（bash 工具经 bwrap 执行；engine="off" 时 fail-closed）
                "sandbox": {
                    "dir": sandbox_dir,
                    "engine": settings.sandbox_engine,
                    "limits": {
                        "memory_mb": settings.sandbox_memory_mb,
                        "nproc": settings.sandbox_nproc,
                        "cpu_s": settings.sandbox_cpu_s,
                    },
                },
            }
        }
        thinking: list[str] = []
        coalescer = ThinkStreamCoalescer()
        deferred_completed: list[dict] = []

        async def _emit_think_delta(text: str) -> None:
            """下发合并后的 thought.stream=think 瞬态帧。"""
            await _send(
                websocket,
                state,
                _frame(
                    session_id,
                    "thought",
                    state.cursor,
                    {"text": text, "stream": "think"},
                ),
            )

        async def _flush_think() -> None:
            chunk = coalescer.flush()
            if chunk:
                await _emit_think_delta(chunk)

        async for mode, chunk in _AGENT.astream(
            serializable, config=graph_config, resume=resume_answer
        ):
            if mode == "custom":
                kind = str(chunk.get("kind") or "")
                text = str(chunk.get("text") or "")
                if kind == "content" and text:
                    await _flush_think()
                    await SESSION_CONNECTION_HUB.broadcast_chunk(
                        session_id,
                        lambda cursor, text=text: _frame(
                            session_id,
                            "assistant_delta",
                            cursor,
                            {"role": "assistant", "text": text},
                        ),
                    )
                elif kind == "reasoning" and text:
                    thinking.append(text)
                    merged = coalescer.push(text)
                    if merged:
                        await _emit_think_delta(merged)
                elif kind == "tool_progress":
                    # 工具进度为瞬态帧：不占 event_id、不落库；断线后只以最终
                    # tool_result 恢复卡片，避免重放半截执行状态或敏感输出。
                    payload = {
                        "call_id": str(chunk.get("call_id") or ""),
                        "name": str(chunk.get("name") or ""),
                        "stage": str(chunk.get("stage") or "executing"),
                        "message": str(chunk.get("message") or "工具正在执行"),
                    }
                    await SESSION_CONNECTION_HUB.broadcast_chunk(
                        session_id,
                        lambda cursor, payload=payload: _frame(
                            session_id, "tool_progress", cursor, payload
                        ),
                    )
                elif kind == "tool_output_delta":
                    # handler 仅能通过 ToolNode 的 4KB 受控窗口写入；此处不接受
                    # 任何模型 Observation、完整文件或未脱敏的错误正文。
                    payload = {
                        "call_id": str(chunk.get("call_id") or ""),
                        "name": str(chunk.get("name") or ""),
                        "seq": int(chunk.get("seq") or 0),
                        "channel": str(chunk.get("channel") or "result"),
                        "text": str(chunk.get("text") or ""),
                        "start_line": int(chunk.get("start_line") or 1),
                    }
                    if payload["call_id"] and payload["text"]:
                        await SESSION_CONNECTION_HUB.broadcast_chunk(
                            session_id,
                            lambda cursor, payload=payload: _frame(
                                session_id, "tool_output_delta", cursor, payload
                            ),
                        )
                continue
            # 澄清卡 interrupt() 中断帧：翻译为 clarify 事件并保存待恢复状态
            if isinstance(chunk, dict) and "__interrupt__" in chunk:
                payload = chunk["__interrupt__"][0].value
                if isinstance(payload, dict) and payload.get("type") == "clarify":
                    await _handle_clarify_interrupt(
                        db, websocket, state, session_id, thread_id, payload
                    )
                continue
            # updates 模式：按节点边界消费 pending_events，统一 emit
            for event in iter_pending_events(chunk):
                if event.get("kind") == "response.completed":
                    # completed 必须是本轮最后一条持久事件；think_final 要插在它前面。
                    deferred_completed.append(event)
                    continue
                await _flush_think()
                await _translate_event(
                    db,
                    websocket,
                    state,
                    session_id,
                    profile,
                    event,
                    user=turn_user,
                )

        await _flush_think()
        if thinking:
            await _emit_persistent(
                db,
                websocket,
                state,
                session_id,
                "thought",
                {"text": "".join(thinking), "stream": "think_final"},
            )
        for event in deferred_completed:
            await _translate_event(
                db,
                websocket,
                state,
                session_id,
                profile,
                event,
                user=turn_user,
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
        logger.exception("Agent 回合内部异常 session=%s exc=%s", session_id, exc)
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


async def _handle_stop(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    active_turn: asyncio.Task[None] | None,
) -> None:
    """/stop 即时中断：置位会话 abort 并取消当前回合（不可恢复，§2.5）。

    ``interrupt()`` 是可恢复暂停，不替代取消；/stop 不取消已入队的任务。
    """
    abort = _SESSION_ABORTS.get(session_id)
    if abort:
        abort.set()
    if active_turn and not active_turn.done():
        active_turn.cancel()
    await _emit_persistent(
        db,
        websocket,
        state,
        session_id,
        "response.completed",
        {"finish_reason": "cancelled", "role": "assistant"},
    )


async def _handle_compact(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session: AgentSession,
    user: User,
) -> None:
    """/compact：会话级上下文副作用，仅会话 owner 可执行（API.md §4.4）。

    M2 ``summarize`` 产出摘要（保留最近 6 条、≤2000 字符、不删除原始记录），
    M3 ``write_summary`` 写 ``sessions.compact_summary``，窗口游标
    ``compact_keep_from`` 指向保留起点（CX-6/MEM-3 原始优先）。
    """
    if session.user_id != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "仅会话负责人可执行 /compact")
    rows = (
        db.query(Message)
        .filter(Message.session_id == session.id, Message.role.in_(("user", "assistant")))
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    messages = [
        {"role": row.role, "content": row.content, "source_id": row.source_id}
        for row in rows
    ]
    summary, kept_ids = summarize([dict(message) for message in messages])
    write_summary(db, session.id, summary)
    session.compact_keep_from = kept_ids[0] if kept_ids else None
    db.commit()
    await _emit_persistent(
        db,
        websocket,
        state,
        session.id,
        "assistant_message",
        {"text": "会话已压缩：保留最近 6 条原始消息，更早内容已生成摘要。", "role": "assistant"},
    )


async def _handle_cancel(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session: AgentSession,
    user: User,
) -> None:
    """/cancel：取消本会话非终态任务（权限同 REST cancel，API.md §4.4）。"""
    from ..harness.memory.episodic import get_active_tasks

    actives = get_active_tasks(db, session.id)
    if not actives:
        raise AppError(ErrorCode.VALIDATION, "当前会话没有可取消的任务")
    task = actives[0]
    result = cancel_task_safe(
        {"task_id": task.id},
        ToolExecutionContext(
            session_id=session.id,
            user_id=user.id,
            thread_id=session.id,
            call_id="ws-slash-cancel",
        ),
    )
    await _emit_persistent(
        db,
        websocket,
        state,
        session.id,
        "tool_result",
        {
            "name": "task.cancel",
            "ok": True,
            "data": {
                "task_id": result.get("task_id"),
                "status": result.get("status"),
                "kind": result.get("kind"),
            },
        },
        task_id=str(result.get("task_id") or "") or None,
    )


async def _handle_stress(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session: AgentSession,
    user: User,
) -> None:
    """/stress：发出质量任务确认卡且 with_stress=true，禁止 kind=stress。"""
    from ..harness.memory import read_prefs
    from ..harness.memory.episodic import get_active_tasks

    fresh = (
        db.query(AgentSession)
        .filter(AgentSession.id == session.id)
        .with_for_update()
        .first()
    )
    if not fresh:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    if fresh.pending_confirm:
        raise AppError(ErrorCode.CONCURRENCY, "会话存在待确认任务，请先确认或取消")
    if get_active_tasks(db, session.id):
        raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务")
    spec = build_slash_stress_spec(read_prefs(db, user.id))
    drop_stale_asset_ids(db, spec)
    if spec.get("kind") == "stress":
        raise AppError(ErrorCode.VALIDATION, "对话路径不得发出压测确认卡")
    outgoing = dict(spec)
    author = _confirm_author_payload(user)
    if author:
        outgoing["confirm_author"] = author
    _persist_pending_confirm(db, session.id, outgoing)
    await _emit_persistent(db, websocket, state, session.id, "confirm", outgoing)


async def _handle_clarify_interrupt(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session_id: str,
    thread_id: str,
    payload: dict,
) -> None:
    """澄清卡中断帧翻译：持久化 clarify 事件并保存待恢复状态。

    图已 ``interrupt()`` 暂停（回合自然结束）；``_SESSION_CLARIFY`` 保存
    ``{id, thread_id}``，待 ``clarify_reply`` 到达后以 ``Command(resume)``
    恢复同一 thread（M9 §3.5.1）。澄清卡不建任务、不写 pending_confirm。
    """
    clarify_id = str(payload.get("id") or "")
    _SESSION_CLARIFY[session_id] = {
        "id": clarify_id,
        "thread_id": thread_id,
    }
    await _emit_persistent(
        db,
        websocket,
        state,
        session_id,
        "clarify",
        {
            "id": clarify_id,
            "question": str(payload.get("question") or ""),
            "options": payload.get("options"),
        },
    )


async def _handle_clarify_reply(
    db: Session,
    websocket: WebSocket,
    state: _ConnectionState,
    session: AgentSession,
    payload: Any,
    active_turn: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    """澄清卡回复：校验 id 匹配后以 Command(resume) 恢复图（不唤醒 confirm）。"""
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.VALIDATION, "clarify_reply payload 必须是对象")
    pending = _SESSION_CLARIFY.get(session.id)
    if pending is None:
        raise AppError(ErrorCode.VALIDATION, "无待回复的澄清卡")
    if str(payload.get("id") or "") != pending["id"]:
        raise AppError(ErrorCode.VALIDATION, "澄清卡已失效，请刷新后重试")
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise AppError(ErrorCode.VALIDATION, "回复内容不能为空")
    if active_turn and not active_turn.done():
        raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")
    _SESSION_CLARIFY.pop(session.id, None)
    abort = asyncio.Event()
    _SESSION_ABORTS[session.id] = abort
    task = asyncio.create_task(
        _run_turn(
            session.id,
            websocket,
            state,
            abort,
            user_id=session.user_id,
            resume={"thread_id": pending["thread_id"], "answer": answer.strip()},
        ),
        name=f"agent-turn-{session.id}",
    )
    task.add_done_callback(
        lambda _task: _SESSION_ABORTS.pop(session.id, None)
    )
    return task


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
    if not isinstance(text, str):
        raise AppError(ErrorCode.VALIDATION, "消息内容格式不正确")
    if active_turn and not active_turn.done():
        raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")

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
    # 新用户消息作废未回复的澄清卡（澄清与新一轮输入互斥）
    _SESSION_CLARIFY.pop(session.id, None)
    abort = asyncio.Event()
    _SESSION_ABORTS[session.id] = abort
    task = asyncio.create_task(
        _run_turn(session.id, websocket, state, abort, user_id=user.id),
        name=f"agent-turn-{session.id}",
    )
    task.add_done_callback(
        lambda _task: _SESSION_ABORTS.pop(session.id, None)
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
                                )
                                continue
                            if stripped.startswith("/compact"):
                                # /compact 会话级副作用：仅 owner 可执行（API.md §4.4）
                                await _handle_compact(db, websocket, state, session, user)
                                continue
                            if stripped.startswith("/cancel"):
                                # /cancel：只取消本会话非终态任务，不进图
                                await _handle_cancel(db, websocket, state, session, user)
                                continue
                            if stripped.startswith("/stress"):
                                # /stress：质量任务卡 + with_stress，禁止 kind=stress
                                await _handle_stress(db, websocket, state, session, user)
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
                elif event == "clarify_reply":
                    # 澄清卡回复：校验 id 后以 Command(resume) 恢复图
                    active_turn = await _handle_clarify_reply(
                        db,
                        websocket,
                        state,
                        session,
                        message.get("payload"),
                        active_turn,
                    )
                elif event == "confirm_ack":
                    # 确认卡回执：收包循环直连，不唤醒图（OR-8）
                    result = handle_confirm_ack(
                        db,
                        session.id,
                        user.id,
                        message.get("payload") if isinstance(message.get("payload"), dict) else {},
                    )
                    await _emit_persistent(
                        db,
                        websocket,
                        state,
                        session.id,
                        "confirm_ack",
                        {"ok": result.ok, "task_id": result.task_id, "message": result.message},
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
                        "tool_result",
                        {
                            "name": "task.cancel",
                            "ok": True,
                            "data": {
                                "task_id": result.get("task_id"),
                                "status": result.get("status"),
                                "kind": result.get("kind"),
                            },
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
        if heartbeat_task:
            heartbeat_task.cancel()
        if forward_task:
            forward_task.cancel()
        if session:
            SESSION_CONNECTION_HUB.unregister(session.id, connection_id)
        db.close()
