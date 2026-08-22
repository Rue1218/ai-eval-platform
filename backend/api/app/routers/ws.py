"""Agent WebSocket：短票鉴权、Harness 调度、确认卡入队与断线补发。

契约依据：docs/AI测试与评估平台-API.md §4 与 PRD 5.1.3。事件统一使用
``{"event", "session_id", "task_id", "event_id", "ts", "payload"}`` 公共头，
上行仅 ``user_message`` / ``confirm_ack`` / ``cancel_task`` 三类消息。
长任务规划/工具/复核由 ``agent.harness`` 在 asyncio.Task 中执行，本模块收包循环不得 await 整轮。
"""

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agent.harness import (
    abort_running_turn,
    deep_merge,
    dispatch_user_message,
    handle_cancel_task,
    handle_confirm_ack,
)
from ..agent.log import agent_trace
from ..agent.plan import classify_intent_l0
from ..db import SessionLocal
from ..errors import AppError
from ..models import (
    Message,
    Setting,
    StoredFile,
    User,
    WsEvent,
)
from ..models import Session as AgentSession
from ..security import TOKEN_TYPE_WS, decode_token
from ..session_access import find_visible_session
from ..session_connections import SESSION_CONNECTION_HUB

router = APIRouter(tags=["ws"])
logger = logging.getLogger("ai-eval.ws")


class _ConnState:
    """单连接的事件游标与发送锁。

    `_emit` 直连发送与后台转发循环共用同一把锁与同一个游标，
    保证 Worker 进程外写入的事件与 Agent 即时回复不会交错或重复下发。
    """

    def __init__(self, cursor: int = 0) -> None:
        self.cursor = cursor
        self.lock = asyncio.Lock()


# 已消费的 WS 短票 jti -> 票据到期时间戳（PRD：5 分钟单次短票）。
# 待确认卡落库 sessions.pending_confirm，不再使用进程内字典。
_USED_WS_TICKETS: dict[str, float] = {}

# 已消费票据记录的清理阈值，避免长期运行下字典无限增长
_USED_TICKETS_GC_THRESHOLD = 1024


def _consume_ws_ticket(payload: dict) -> bool:
    """消费短票的单次使用标识，同一 jti 第二次连接直接拒绝。

    票据必须携带 ``jti``（缺失视为非法票）；到期记录在后续调用中
    机会式清理。函数为同步无 await，单事件循环内天然原子。
    """
    jti = payload.get("jti")
    if not jti:
        return False
    now = time.time()
    if len(_USED_WS_TICKETS) > _USED_TICKETS_GC_THRESHOLD:
        for key, expire_at in list(_USED_WS_TICKETS.items()):
            if expire_at <= now:
                _USED_WS_TICKETS.pop(key, None)
    if jti in _USED_WS_TICKETS:
        return False
    # 记录 5 分钟有效窗口（与票面 exp 一致），窗口过后可被清理
    _USED_WS_TICKETS[jti] = now + 300
    return True

def _user_from_ticket(ticket: str) -> User | None:
    """验证 WebSocket 短票、单次消费、账号状态和改密后的认证版本。"""
    try:
        payload = decode_token(ticket)
    except Exception:
        return None
    if payload.get("type") != TOKEN_TYPE_WS:
        return None
    # 单次短票：同一票据建立过连接即作废，重连须重新领票
    if not _consume_ws_ticket(payload):
        return None
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == payload.get("sub"), User.disabled.is_(False)).first()
        if not user or payload.get("av") != user.auth_version:
            return None
        return user
    finally:
        db.close()


def _next_event_id(db: Session, session_id: str) -> int:
    """在锁定会话行后获取该会话的下一个单调事件号。"""
    db.query(AgentSession).filter(AgentSession.id == session_id).with_for_update().one()
    current = db.query(func.max(WsEvent.event_id)).filter(WsEvent.session_id == session_id).scalar()
    return (current or 0) + 1


def _event_body(session_id: str, event_id: int, event: str, payload: dict, task_id: str | None, ts: datetime) -> dict:
    """构造 API.md §4.2 规定的标准事件公共头，payload 始终嵌套。"""
    return {
        "event": event,
        "session_id": session_id,
        "task_id": task_id,
        "event_id": event_id,
        "ts": ts.isoformat(),
        "payload": payload,
    }


async def _emit(
    db: Session,
    ws: WebSocket,
    session_id: str,
    event: str,
    payload: dict,
    *,
    task_id: str | None = None,
    state: _ConnState | None = None,
) -> int:
    """持久化标准 WS 事件后向当前连接发送同一份公开载荷。

    传入 state 时在连接锁内完成「取号 → 落库 → 发送 → 推进游标」，
    与后台转发循环互斥，避免同一事件被直连与转发各发一次。
    """
    if state is None:
        event_id = _next_event_id(db, session_id)
        now = datetime.now(UTC)
        db.add(
            WsEvent(
                session_id=session_id,
                task_id=task_id,
                event_id=event_id,
                event=event,
                payload=payload,
                ts=now,
            )
        )
        db.commit()
        try:
            await ws.send_json(_event_body(session_id, event_id, event, payload, task_id, now))
        except Exception:
            logger.debug("WS 连接已断开，事件已落库但未实时投递: session_id=%s, event_id=%d", session_id, event_id)
        return event_id
    async with state.lock:
        event_id = _next_event_id(db, session_id)
        now = datetime.now(UTC)
        db.add(
            WsEvent(
                session_id=session_id,
                task_id=task_id,
                event_id=event_id,
                event=event,
                payload=payload,
                ts=now,
            )
        )
        db.commit()
        try:
            await ws.send_json(_event_body(session_id, event_id, event, payload, task_id, now))
        except Exception:
            logger.debug("WS 连接已断开，事件已落库但未实时投递: session_id=%s, event_id=%d", session_id, event_id)
        state.cursor = event_id
        return event_id


def _owned_session(db: Session, session_id: str, user_id: str) -> AgentSession | None:
    """读取当前成员可访问的未删除会话，私有会话不泄露给协作者。"""
    return find_visible_session(db, session_id, user_id)


def _assert_attachments(db: Session, attachments: list[dict]) -> list[str]:
    """校验上行附件为 ``[{file_id}]`` 结构，并确保文件已真实上传。

    返回去重后的 file_id 列表；伪造或缺失的 file_id 会触发 ValueError。
    """
    file_ids = [item.get("file_id") for item in attachments if isinstance(item, dict) and item.get("file_id")]
    if len(file_ids) != len(attachments):
        raise ValueError("附件格式无效")
    if file_ids:
        count = db.query(StoredFile).filter(StoredFile.id.in_(file_ids)).count()
        if count != len(set(file_ids)):
            raise ValueError("附件不存在")
    return file_ids


def _message_payload(message: Message, user: User) -> dict:
    """构造持久化用户消息事件，供协作者实时回显并按幂等键去重。"""
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "attachments": message.attachments or [],
        "author_id": message.author_id,
        "author": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
        },
        "client_message_id": message.client_message_id,
        "created_at": message.created_at.isoformat(),
    }


def _deep_merge(base: dict, patch: dict) -> dict:
    """对确认卡 patch 做递归深合并，保留用户未修改的嵌套默认值。"""
    return deep_merge(base, patch)


def _classify_intent(text: str) -> str:
    """L0 规则意图（单测与降级路径共用）。"""
    intent, _stress = classify_intent_l0(text)
    return intent


def _parse_llm_json(text: str) -> dict:
    """从模型输出中容错提取 JSON 对象（允许 markdown 代码块、首尾文字或纯文本兜底）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    # 容错：如果模型直接输出了自然语言回复（如问候/自我介绍/解答）而未套 JSON，
    # 绝不能粗暴丢弃，将其视为 chat 意图的自然语言 reply 返回
    if cleaned:
        agent_trace(f"LLM 输出非标准 JSON，自动提取为纯文本 chat 回复 chars={len(cleaned)}")
        return {"reply": cleaned, "intent": "chat"}
    raise ValueError("模型未返回任何有效文本内容")


def _match_profiles(items: list[dict], names: list[str]) -> list[str]:
    """把模型提到的协议档名称/ID 映射为已知 ID；未匹配或未提及时回退到首个。"""
    if not items:
        return []
    if names:
        picked: list[str] = []
        for name in names:
            hit = next(
                (p for p in items if p["id"] == name or name in p["name"] or p["name"] in name),
                None,
            )
            if hit and hit["id"] not in picked:
                picked.append(hit["id"])
        if picked:
            return picked
    return [items[0]["id"]]


def _match_dataset(items: list[dict], name: str) -> str | None:
    """把模型提到的数据集名称/ID 映射为已知 ID；未匹配或未提及时回退到首个。"""
    if not items:
        return None
    if name:
        hit = next(
            (d for d in items if d["id"] == name or name in d["name"] or d["name"] in name),
            None,
        )
        if hit:
            return hit["id"]
    return items[0]["id"]


_REPLY_KEY_RE = re.compile(r'"reply"\s*:\s*"')


def _visible_reply(buf: str) -> str:
    """从累积的模型输出中提取 ``reply`` 字段的当前可见文本。

    系统提示词要求 reply 字段置于 JSON 首位，因此流式期间即可边生成边展示：
    找到 ``"reply": "`` 后逐字符扫描（处理转义），直至值闭合引号或缓冲区末尾。
    尾部不完整的转义序列（如单独的反斜杠或截断的 ``\\uXXXX``）暂不展示，
    待后续增量到达再补全；未出现 reply 键时返回空串（自然降级为终帧整体渲染）。
    """
    m = _REPLY_KEY_RE.search(buf)
    if not m:
        return ""
    i = m.end()
    out: list[str] = []
    while i < len(buf):
        ch = buf[i]
        if ch == "\\":
            if i + 1 >= len(buf):
                break  # 转义不完整：尾部暂不展示
            nxt = buf[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            elif nxt == "u":
                if i + 6 <= len(buf):
                    try:
                        out.append(chr(int(buf[i + 2 : i + 6], 16)))
                        i += 6
                        continue
                    except ValueError:
                        pass
                break  # \uXXXX 不完整：尾部暂不展示
            else:
                out.append(nxt)
            i += 2
            continue
        if ch == '"':
            break  # 值闭合：可见文本到此为止
        out.append(ch)
        i += 1
    return "".join(out)


def _stream_frame(session_id: str, cursor: int, delta: str) -> dict:
    """构造流式增量瞬态帧：复用 thought 事件名，payload 携带 stream=chunk。

    与 pong 同策略：不写入 ws_events、不占用单调事件号，断线重连时
    不会回放半截增量；``event_id`` 复用连接游标仅为满足公共头结构。
    """
    return {
        "event": "thought",
        "session_id": session_id,
        "task_id": None,
        "event_id": cursor,
        "ts": datetime.now(UTC).isoformat(),
        "payload": {"text": delta, "stream": "chunk"},
    }


def _think_frame(session_id: str, cursor: int, delta: str) -> dict:
    """构造思考链增量瞬态帧：payload 携带 stream=think。

    推理模型的前置思考过程：前端渲染进可展开/收起的思考卡，
    同样不落库、不占事件号、断线不回放。
    """
    return {
        "event": "thought",
        "session_id": session_id,
        "task_id": None,
        "event_id": cursor,
        "ts": datetime.now(UTC).isoformat(),
        "payload": {"text": delta, "stream": "think"},
    }


async def _handle_user_message(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    user: User,
    text: str,
    attachments: list[dict],
    client_message_id: str | None,
    state: _ConnState,
) -> None:
    """落库用户消息后把 Harness 丢到 asyncio.Task，不阻塞收包循环。"""
    file_ids = _assert_attachments(db, attachments)
    if client_message_id:
        existing = (
            db.query(Message)
            .filter(
                Message.session_id == session.id,
                Message.client_message_id == client_message_id,
            )
            .first()
        )
        if existing:
            # 浏览器断线后重发相同幂等键：只补发已保存的气泡，不再触发第二轮 Harness。
            await _emit(
                db,
                ws,
                session.id,
                "message",
                _message_payload(existing, user),
                state=state,
            )
            return
    message = Message(
        session_id=session.id,
        role="user",
        content=text,
        attachments=file_ids,
        author_id=user.id,
        client_message_id=client_message_id,
    )
    db.add(message)
    session.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    # 用户气泡必须是持久化事件；否则协作者只有刷新历史才能看见对方发言。
    await _emit(
        db,
        ws,
        session.id,
        "message",
        _message_payload(message, user),
        state=state,
    )
    agent_trace(f"收到 user_message session={session.id[:8]} chars={len(text)}")

    async def emit_busy(event: str, payload: dict, *, task_id: str | None = None) -> int:
        return await _emit(db, ws, session.id, event, payload, task_id=task_id, state=state)

    def emit_factory(hdb: Session):
        async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
            stream_kind = payload.get("stream") if isinstance(payload, dict) else None
            if stream_kind in {"chunk", "think"}:
                # 瞬态流式帧：不落库、不占事件号，避免断线回放半截增量
                delta = str(payload.get("text") or "")
                if stream_kind == "chunk":
                    # 正文增量对团队共享会话的全部在线成员可见；每个连接独立持锁发送。
                    def _build_chunk_frame(cursor: int) -> dict:
                        frame = _stream_frame(session.id, cursor, delta)
                        if task_id:
                            frame["task_id"] = task_id
                        return frame

                    await SESSION_CONNECTION_HUB.broadcast_chunk(session.id, _build_chunk_frame)
                else:
                    # 原始推理思考链只保留给发起本轮生成的连接，不向协作者泄露。
                    frame = _think_frame(session.id, state.cursor, delta)
                    if task_id:
                        frame["task_id"] = task_id
                    try:
                        async with state.lock:
                            await ws.send_json(frame)
                    except Exception:
                        logger.debug("WS 思考帧未投递 session_id=%s", session.id)
                return state.cursor
            return await _emit(hdb, ws, session.id, event, payload, task_id=task_id, state=state)

        return emit

    await dispatch_user_message(
        session_id=session.id,
        user_id=user.id,
        text=text,
        attachments=file_ids,
        message_id=message.id,
        is_session_owner=session.user_id == user.id,
        emit_busy=emit_busy,
        emit_factory=emit_factory,
    )


async def _handle_confirm_ack(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    user: User,
    ok: bool,
    patch: dict | None,
    state: _ConnState,
) -> None:
    """处理确认卡回执：交给 Harness（校验失败保留 pending_confirm）。"""
    db.refresh(session)

    async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
        return await _emit(db, ws, session.id, event, payload, task_id=task_id, state=state)

    await handle_confirm_ack(db, session=session, user=user, ok=ok, patch=patch, emit=emit)


async def _handle_cancel_task(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    user: User,
    task_id: str,
    state: _ConnState,
) -> None:
    """取消当前成员的非终态任务。"""

    async def emit(event: str, payload: dict, *, task_id: str | None = None) -> int:
        return await _emit(db, ws, session.id, event, payload, task_id=task_id, state=state)

    await handle_cancel_task(db, session=session, user=user, task_id=task_id, emit=emit)


async def _replay_events(db: Session, ws: WebSocket, session_id: str, after_id: int) -> int:
    """断线重连时按 last_event_id 补发会话内缺失的事件，返回补发到的最大事件号。"""
    rows = (
        db.query(WsEvent)
        .filter(WsEvent.session_id == session_id, WsEvent.event_id > after_id)
        .order_by(WsEvent.event_id)
        .all()
    )
    for row in rows:
        await ws.send_json(_event_body(session_id, row.event_id, row.event, row.payload, row.task_id, row.ts))
    return rows[-1].event_id if rows else after_id


def _pong_body(session_id: str, cursor: int) -> dict:
    """构造应用层心跳 pong 事件（API.md §4.3：payload 为空、前端不渲染）。

    pong 不写入 ws_events、不占用单调事件号；``event_id`` 复用连接当前
    游标，仅用于满足公共头结构，前端判活后按去重规则忽略。
    """
    return {
        "event": "pong",
        "session_id": session_id,
        "task_id": None,
        "event_id": cursor,
        "ts": datetime.now(UTC).isoformat(),
        "payload": {},
    }


async def _heartbeat_loop(ws: WebSocket, session_id: str, state: _ConnState, interval_s: float) -> None:
    """按配置周期发送应用层 pong 心跳（契约：前端不发明 JSON ping）。

    心跳在连接锁内发送，与转发循环 / 直发互斥避免帧交错；
    发送失败（连接关闭）时静默退出，由主循环 finally 统一清理。
    """
    while True:
        await asyncio.sleep(interval_s)
        try:
            async with state.lock:
                await ws.send_json(_pong_body(session_id, state.cursor))
        except Exception:
            logger.debug("会话 %s 的心跳循环退出", session_id, exc_info=True)
            return


def _heartbeat_interval(db: Session) -> float:
    """读取 settings.runtime.ws_ping_s（默认 15s，允许 5–300s）。"""
    row = db.query(Setting).filter(Setting.key == "runtime").first()
    value = (row.value or {}).get("ws_ping_s") if row else None
    if isinstance(value, int | float) and 5 <= value <= 300:
        return float(value)
    return 15.0


async def _forward_loop(
    ws: WebSocket,
    session_id: str,
    user_id: str,
    state: _ConnState,
) -> None:
    """后台转发循环：把 Worker 等进程外写入 ws_events 的新事件推送到当前连接。

    Worker 执行长任务时只向 ws_events 表追加 progress/report/error 事件，
    本循环按游标增量检出并在连接锁内发送，与 _emit 的直连发送互斥去重。
    连接关闭（发送抛异常）时静默退出，由主循环的 finally 统一清理。
    """
    while True:
        await asyncio.sleep(1.0)
        db: Session = SessionLocal()
        try:
            # 分享被收回或会话被软删除时，已连接协作者也必须立即失去事件读取能力。
            if not _owned_session(db, session_id, user_id):
                try:
                    async with state.lock:
                        await ws.close(code=4404)
                except Exception:
                    pass
                return
            async with state.lock:
                rows = (
                    db.query(WsEvent)
                    .filter(WsEvent.session_id == session_id, WsEvent.event_id > state.cursor)
                    .order_by(WsEvent.event_id)
                    .all()
                )
                for row in rows:
                    await ws.send_json(_event_body(session_id, row.event_id, row.event, row.payload, row.task_id, row.ts))
                    state.cursor = row.event_id
        except Exception:
            # 连接已关闭或数据库瞬时故障：退出转发，等待主循环收尾
            logger.debug("会话 %s 的事件转发循环退出", session_id, exc_info=True)
            return
        finally:
            db.close()


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    """建立 Agent 长连接，实时事件只做控制面而不执行长任务。"""
    ticket = websocket.query_params.get("ticket", "")
    user = _user_from_ticket(ticket)
    if not user:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    db: Session = SessionLocal()
    forwarder: asyncio.Task | None = None
    heartbeat: asyncio.Task | None = None
    connection_id: str | None = None
    session_id: str | None = None
    try:
        requested_session_id = websocket.query_params.get("session_id")
        if requested_session_id:
            session = _owned_session(db, requested_session_id, user.id)
            if not session:
                await websocket.close(code=4404)
                return
        else:
            session = AgentSession(user_id=user.id, title="新会话")
            db.add(session)
            db.commit()
            db.refresh(session)
        session_id = session.id

        try:
            last_event_id = max(0, int(websocket.query_params.get("last_event_id", "0") or "0"))
        except ValueError:
            last_event_id = 0
        state = _ConnState(cursor=last_event_id)
        if last_event_id:
            state.cursor = await _replay_events(db, websocket, session_id, last_event_id)
        # 新会话不再下发欢迎语：前端空态已有引导文案与快捷芯片，
        # 服务端重复欢迎语会造成冗余消息；首条消息由用户触发后正常回复。

        # 启动后台转发：Worker 回推的 progress/report/error 经 ws_events 表送达本连接
        connection_id = uuid.uuid4().hex
        SESSION_CONNECTION_HUB.register(connection_id, session_id, user.id, websocket, state)
        forwarder = asyncio.create_task(_forward_loop(websocket, session_id, user.id, state))
        # 启动应用层心跳：周期发送 pong 供前端判活（前端不发 JSON ping）
        heartbeat = asyncio.create_task(
            _heartbeat_loop(websocket, session_id, state, _heartbeat_interval(db))
        )

        while True:
            raw = await websocket.receive_text()
            # 会话可能在连接存活期间被收回共享或软删除；收包前再次校验权限。
            fresh_session = _owned_session(db, session_id, user.id)
            if not fresh_session:
                await websocket.close(code=4404)
                return
            session = fresh_session
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "消息格式无效"}, state=state)
                continue

            event = message.get("event")
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

            if event == "user_message":
                text = str(payload.get("text", "")).strip()
                attachments = payload.get("attachments", [])
                client_message_id = payload.get("client_message_id")
                if not isinstance(attachments, list):
                    await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "attachments 格式无效"}, state=state)
                    continue
                if client_message_id is not None and (
                    not isinstance(client_message_id, str)
                    or not client_message_id.strip()
                    or len(client_message_id) > 128
                ):
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": "VALIDATION", "message": "client_message_id 格式无效"},
                        state=state,
                    )
                    continue
                if not text and not attachments:
                    await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "消息不能为空"}, state=state)
                    continue
                try:
                    await _handle_user_message(
                        db,
                        websocket,
                        session,
                        user,
                        text,
                        attachments,
                        client_message_id.strip() if isinstance(client_message_id, str) else None,
                        state,
                    )
                except AppError as exc:
                    agent_trace(f"user_message AppError code={exc.code.value}")
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": exc.code.value, "message": exc.message},
                        state=state,
                    )
                except ValueError as exc:
                    await _emit(db, websocket, session_id, "error", {"code": "NOT_FOUND", "message": str(exc)}, state=state)
                except Exception:
                    # DB 瞬断等未预期异常：归一 INTERNAL 错误事件，避免异常冒泡踢断整条连接
                    db.rollback()
                    logger.exception("会话 %s 处理 user_message 失败", session_id)
                    await _emit(db, websocket, session_id, "error", {"code": "INTERNAL", "message": "消息处理失败，请稍后重试"}, state=state)
                continue

            if event == "confirm_ack":
                ok = bool(payload.get("ok"))
                patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else None
                try:
                    await _handle_confirm_ack(db, websocket, session, user, ok, patch, state)
                except AppError as exc:
                    agent_trace(f"confirm_ack AppError code={exc.code.value}")
                    await _emit(
                        db,
                        websocket,
                        session_id,
                        "error",
                        {"code": exc.code.value, "message": exc.message},
                        state=state,
                    )
                except IntegrityError:
                    # 双连接同时确认同一会话：撞 uq_tasks_active_session 唯一索引，归一为并发冲突
                    db.rollback()
                    await _emit(db, websocket, session_id, "error", {"code": "CONCURRENCY", "message": "当前会话已有未完成任务，请勿重复提交。"}, state=state)
                except Exception:
                    db.rollback()
                    logger.exception("会话 %s 处理 confirm_ack 失败", session_id)
                    await _emit(db, websocket, session_id, "error", {"code": "INTERNAL", "message": "确认处理失败，请稍后重试"}, state=state)
                continue

            if event == "cancel_task":
                task_id = str(payload.get("task_id", ""))
                try:
                    await _handle_cancel_task(db, websocket, session, user, task_id, state)
                except Exception:
                    db.rollback()
                    logger.exception("会话 %s 处理 cancel_task 失败", session_id)
                    await _emit(db, websocket, session_id, "error", {"code": "INTERNAL", "message": "取消请求处理失败，请稍后重试"}, state=state)
                continue

            await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "不支持的消息类型"}, state=state)
    except WebSocketDisconnect:
        if session_id:
            abort_running_turn(session_id, reason="disconnect", user_id=user.id)
    finally:
        if forwarder is not None:
            forwarder.cancel()
        if heartbeat is not None:
            heartbeat.cancel()
        if connection_id is not None and session_id is not None:
            SESSION_CONNECTION_HUB.unregister(session_id, connection_id)
        db.close()
