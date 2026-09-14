"""Agent WebSocket 事件发射层（自 ``ws.py`` 抽出）。

承载连接状态（发送锁 + 事件游标）、§4.2 公共事件头构造、事件词汇表版本护栏、
持久化事件落库与 Hub 扇出、业务错误收敛。本模块只依赖 ORM、连接 Hub 与纯函数，
不持有回合调度与业务 handler 逻辑，可脱离 ws 连接生命周期独立测试。

``ws.py`` 以同名符号 re-export 本模块成员：既有调用点与测试 patch
（``monkeypatch.setattr(ws, "_emit_persistent", ...)`` 等）保持不变——patch 的
是 ws 模块全局名，ws.py 内调用点仍解析到该名。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from shared.event_vocab import EVENT_VERSION, PERSISTENT_KINDS
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import Session as AgentSession
from ..models import WsEvent
from ..session_connections import SESSION_CONNECTION_HUB
from ..time_utils import iso_utc

logger = logging.getLogger("ai-eval.agent-ws")


class _ConnectionState:
    """单个 WebSocket 连接的发送锁与事件游标。"""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.cursor = 0


def _frame(
    session_id: str,
    event: str,
    event_id: int,
    payload: dict[str, Any],
    *,
    task_id: str | None = None,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """构造 API.md §4.2 规定的 WebSocket 公共事件头。

    ``vocab_version``（#4 D2）：词汇表版本（shared.event_vocab.EVENT_VERSION），
    服务端恒发；属可选字段，旧客户端按「忽略未知字段」原则安全跳过。
    """
    return {
        "event": event,
        "session_id": session_id,
        "task_id": task_id,
        "event_id": event_id,
        "ts": iso_utc(ts),
        "vocab_version": EVENT_VERSION,
        "payload": payload,
    }


# #4 D3：落库 payload 内嵌的词汇版本保留字段（转发/回放时剥离，不回显前端）
_EVENT_VERSION_KEY = "event_version"


def _split_event_version(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """取出并剥离落库 payload 的事件词汇版本保留字段（#4 D3）。

    写库侧统一注入 ``event_version``（免 WsEvent 加列/Alembic，向后兼容）；
    读侧（转发/回放）剥离后再广播，前端只见 §4.2 公共头与业务字段。
    历史无版本行返回 ``(原样, None)``——按当前词汇表版本解释（D4 只读兼容）。
    """
    stored = dict(payload or {})
    version = stored.pop(_EVENT_VERSION_KEY, None)
    return stored, str(version) if isinstance(version, str) else None


def _event_vocab_mismatch(event: str, version: str | None) -> str | None:
    """事件词汇表校验（#4 D5 转发护栏）。

    返回 None 放行；否则返回原因（``unknown`` / ``version``）。未知 kind 或
    版本不符均不允许实时转发；历史无版本行（None）按当前版本解释放行。
    """
    if event not in PERSISTENT_KINDS:
        return "unknown"
    if version is not None and version != EVENT_VERSION:
        return "version"
    return None


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
    """写入 ws_events 并发送持久化事件；事件号由数据库历史决定。

    #4 D3：落库 payload 注入 ``event_version`` 词汇版本保留字段（转发/回放侧
    剥离），使 Worker 直写与 api 直写具备同一版本声明面，免 WsEvent 加列。
    """
    stored_payload = dict(payload)
    stored_payload[_EVENT_VERSION_KEY] = EVENT_VERSION
    row: WsEvent | None = None
    event_id = 0
    for attempt in range(2):
        event_id = _next_event_id(db, session_id)
        row = WsEvent(
            session_id=session_id,
            task_id=task_id,
            event_id=event_id,
            event=event,
            payload=stored_payload,
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
    if websocket is None:
        # #3 后台 TTL 扫描等无连接场景：只落库不发送，在线者经 Hub 收到、
        # 离线者断线重连按 last_event_id 回放补齐（事件已持久化即完成职责）。
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
