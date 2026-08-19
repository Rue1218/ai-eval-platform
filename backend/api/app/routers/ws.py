"""Agent WebSocket：短票鉴权、意图拆解、确认卡入队与断线补发。

契约依据：docs/AI测试与评估平台-API.md §4 与 PRD 5.1.3。事件统一使用
``{"event", "session_id", "task_id", "event_id", "ts", "payload"}`` 公共头，
上行仅 ``user_message`` / ``confirm_ack`` / ``cancel_task`` 三类消息。
"""

import asyncio
import json
import logging
import re
import time
from copy import deepcopy
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..llm import call_agent_model
from ..models import (
    AuditLog,
    Dataset,
    Message,
    ProtocolProfile,
    Setting,
    StoredFile,
    Task,
    User,
    WsEvent,
)
from ..models import Session as AgentSession
from ..schemas import TaskCreate
from ..security import TOKEN_TYPE_WS, decode_token

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


# M1 简化：同一 api 进程内保存每会话唯一待确认卡，confirm_ack 时深合并 patch。
# 契约约定「同一会话同一时刻最多一张待确认卡」，进程内字典即可满足；
# 若未来 api 多副本部署，需将待确认卡迁移到数据库或分布式缓存。
_PENDING_CARDS: dict[str, dict] = {}

# 已消费的 WS 短票 jti -> 票据到期时间戳（PRD：5 分钟单次短票）。
# 与 _PENDING_CARDS 同为进程内简化；多副本部署时需迁移到共享存储。
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

# 会话内非终态任务集合，用于阻止会话并发下单（与 tasks.py 保持一致）。
_ACTIVE_STATUSES = {"queued", "running", "awaiting_case_confirm"}
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


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
        await ws.send_json(_event_body(session_id, event_id, event, payload, task_id, now))
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
        await ws.send_json(_event_body(session_id, event_id, event, payload, task_id, now))
        state.cursor = event_id
        return event_id


def _owned_session(db: Session, session_id: str, user_id: str) -> AgentSession | None:
    """读取当前成员拥有的会话，阻止短票跨账号复用会话 ID。"""
    return (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id, AgentSession.user_id == user_id)
        .first()
    )


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


def _deep_merge(base: dict, patch: dict) -> dict:
    """对确认卡 patch 做递归深合并，保留用户未修改的嵌套默认值。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _classify_intent(text: str) -> str:
    """按关键词把用户目标拆解为四种意图之一。"""
    if any(k in text for k in ("PRD", "用例", "测试用例", "生成用例")):
        return "testcase"
    if any(k in text for k in ("RAG", "知识库", "检索", "召回", "LightRAG", "黄金", "命中")):
        return "rag"
    if any(k in text for k in ("解读", "报告")):
        return "report"
    return "benchmark"


def _wants_stress(text: str) -> bool:
    """识别用户是否要求「先评后压」。"""
    return any(k in text for k in ("压测", "加压", "先评后压", "QPS", "qps"))


# 闲聊快速通道：打招呼/感谢/极短确认类消息不经过上游 LLM，直接本地毫秒级回复。
# 避免用户一句「你好」也要等待完整的模型意图识别往返。
_SMALLTALK_RE = re.compile(
    r"^(你好|您好|hi|hello|嗨|哈喽|在吗|在不在|早|早上好|下午好|晚上好|"
    r"谢谢|多谢|辛苦了|感谢|好的|好滴|好嘞|嗯+|哦+|ok|okay|"
    r"收到|明白|了解|知道了|测试)[!！?？。.~\s]*$",
    re.IGNORECASE,
)

# 闲聊快速通道的固定引导文案
_SMALLTALK_REPLY = (
    "你好！我是评测工程师助手，可以帮你发起基准评测（Benchmark）、生成测试用例，"
    "RAG 检索评测将在 M3 上线。请描述你的评测目标，我会先澄清再给你确认卡。"
)


def _is_smalltalk(text: str) -> bool:
    """判定超短打招呼/感谢/确认消息：命中则跳过 LLM 意图识别直接回复。

    仅白名单整词匹配，不影响任何含评测关键词的正常指令。
    """
    return len(text) <= 12 and bool(_SMALLTALK_RE.match(text.strip()))


def _default_run() -> dict:
    """Benchmark / RAG 的默认运行参数，仅含前端确认卡可编辑的核心字段。"""
    return {
        "concurrency": 5,
        "timeout_s": 60,
        "retry": 1,
        "temperature": 0.2,
        "max_tokens": 2048,
        "k": 5,
        "use_judge": False,
    }


def _default_stress() -> dict:
    """先评后压子任务的默认压测参数。"""
    return {"env": "test", "qps": 20, "duration_s": 60, "sla_p99_ms": None}


def _profile_items(db: Session) -> list[dict]:
    """短工具 model.list 的受控发现结果，不含 Key。"""
    rows = db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.desc()).all()
    return [
        {"id": p.id, "name": p.name, "protocol": p.protocol, "model": p.model}
        for p in rows
    ]


def _dataset_items(db: Session) -> list[dict]:
    """短工具 dataset.list 的发现结果。"""
    rows = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
    return [
        {"id": d.id, "name": d.name, "version": d.version, "row_count": d.row_count}
        for d in rows
    ]


async def _call_tool(
    db: Session,
    ws: WebSocket,
    session_id: str,
    name: str,
    arguments: dict,
    data: dict,
    state: _ConnState,
) -> None:
    """发送一对短工具事件：tool_call（pending）后紧跟 tool_result（done）。"""
    await _emit(db, ws, session_id, "tool_call", {"name": name, "arguments": arguments}, state=state)
    await _emit(db, ws, session_id, "tool_result", {"name": name, "ok": True, "data": data}, state=state)


async def _send_confirm(db: Session, ws: WebSocket, session_id: str, card: dict, state: _ConnState) -> None:
    """保存会话唯一待确认卡并发 confirm 事件。"""
    _PENDING_CARDS[session_id] = card
    await _emit(db, ws, session_id, "confirm", card, state=state)


# ─── LLM 驱动的目标解析（失败时回退到下方规则版） ───

_LLM_SYSTEM = (
    "你是 AI 测试评估平台的智能体助手，负责理解用户的评测目标并输出一个 JSON 对象。"
    "只能输出 JSON 本身，不要输出任何解释、代码块或额外文字。JSON 字段：\n"
    '{\n'
    '  "intent": "benchmark" | "testcase" | "rag" | "report" | "chat",\n'
    '  "reply": "给用户的一句话自然语言回复，简洁友好",\n'
    '  "profile_names": ["被测协议档名称或 ID，可选"],\n'
    '  "dataset_name": "数据集名称或 ID，可选",\n'
    '  "with_stress": false\n'
    '}\n'
    "意图判定：benchmark=对比/评测模型或协议档在数据集上的表现（默认意图）；"
    "testcase=根据 PRD/需求生成测试用例；rag=知识库检索评测；report=解读已有评测报告；"
    "chat=与评测无关的闲聊。profile_names 与 dataset_name 仅在 benchmark 且用户明确提到时"
    "从「可用资产」中挑选，不要编造不存在的名称，未提到就留空。with_stress 仅在用户要求压测时置 true。"
)


def _parse_llm_json(text: str) -> dict:
    """从模型输出中容错提取 JSON 对象（允许 markdown 代码块或首尾文字）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回可解析的 JSON 对象")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


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


def _llm_plan(text: str, profiles: list[dict], datasets: list[dict], history: list[dict]) -> dict:
    """在独立线程中调用 Agent 协议档模型，解析出结构化评测目标。

    未配置协议档或上游异常时抛异常，由调用方回退到规则版。
    意图识别输出仅一个小 JSON：max_tokens 压到 512 防推理模型长思考，
    12 秒独立短超时保证最坏情况下快速降级规则版，用户不长时间干等。
    """
    db = SessionLocal()
    try:
        user_payload = {
            "用户消息": text,
            "对话历史": history,
            "可用协议档": [{"id": p["id"], "name": p["name"], "model": p["model"]} for p in profiles],
            "可用数据集": [{"id": d["id"], "name": d["name"]} for d in datasets],
        }
        raw = call_agent_model(
            db,
            system=_LLM_SYSTEM,
            user=json.dumps(user_payload, ensure_ascii=False),
            max_tokens=512,
            timeout_s=12,
        )
        return _parse_llm_json(raw)
    finally:
        db.close()


async def _handle_user_message(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    text: str,
    attachments: list[dict],
    state: _ConnState,
) -> None:
    """LLM 驱动解析用户目标；模型不可用时回退到规则版意图拆解。"""
    file_ids = _assert_attachments(db, attachments)
    db.add(Message(session_id=session.id, role="user", content=text, attachments=file_ids))
    session.updated_at = datetime.now(UTC)
    db.commit()

    # 闲聊快速通道：打招呼/感谢/极短确认无需 LLM 意图识别，毫秒级本地回复
    if _is_smalltalk(text):
        await _emit(db, ws, session.id, "thought", {"text": _SMALLTALK_REPLY}, state=state)
        return

    profiles = _profile_items(db)
    datasets = _dataset_items(db)
    history_rows = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    # PRD F-AGT-05：上下文保留最近 20 条用户/助手消息（超长丢最旧），
    # 系统提示词由 _LLM_SYSTEM 每次调用独立携带、始终保留。
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    plan: dict | None = None
    try:
        plan = await asyncio.to_thread(_llm_plan, text, profiles, datasets, history)
    except Exception:
        logger.info("LLM 目标解析失败，回退规则版", exc_info=True)

    if plan is None:
        await _handle_rule_intent(db, ws, session, text, state)
        return

    intent = str(plan.get("intent") or "benchmark").strip().lower()
    reply = str(plan.get("reply") or "").strip()

    if intent == "benchmark":
        if not profiles:
            await _emit(db, ws, session.id, "thought", {"text": "还没有配置任何协议档，请先到「协议档」页添加被测模型。"}, state=state)
            return
        if not datasets:
            await _emit(db, ws, session.id, "thought", {"text": reply or "已识别为基准评测目标，但当前还没有数据集。请先在「数据集」页上传评测数据。"}, state=state)
            return
        raw_names = plan.get("profile_names") or []
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        profile_ids = _match_profiles(profiles, [str(n) for n in raw_names])
        dataset_id = _match_dataset(datasets, str(plan.get("dataset_name") or ""))
        with_stress = plan.get("with_stress")
        with_stress = with_stress.strip().lower() in ("true", "1", "yes") if isinstance(with_stress, str) else bool(with_stress)
        await _emit(db, ws, session.id, "thought", {"text": reply or "正在梳理基准评测目标，先列出可用协议档与数据集…"}, state=state)
        await _call_tool(db, ws, session.id, "model.list", {}, {"items": profiles}, state)
        await _call_tool(db, ws, session.id, "dataset.list", {}, {"items": datasets}, state)
        await _send_confirm(
            db,
            ws,
            session.id,
            {
                "kind": "benchmark",
                "profile_ids": profile_ids,
                "dataset_id": dataset_id,
                "run": _default_run(),
                "with_stress": with_stress,
                "stress": _default_stress(),
            },
            state,
        )
        return

    if intent == "testcase":
        await _emit(db, ws, session.id, "thought", {"text": reply or "已识别为用例生成目标，请在确认卡中粘贴 PRD / 需求文本。"}, state=state)
        await _send_confirm(db, ws, session.id, {"kind": "testcase", "case_source": {"text": ""}}, state)
        return

    if intent == "rag":
        await _emit(db, ws, session.id, "thought", {"text": reply or "已识别为 RAG 检索评测目标。"}, state=state)
        await _emit(db, ws, session.id, "error", {"code": "NOT_FOUND", "message": "RAG 检索评测能力将在 M3 接入，当前请先使用基准评测。"}, state=state)
        return

    if intent == "report":
        await _emit(db, ws, session.id, "thought", {"text": reply or "报告解读能力将在 M4 接入。"}, state=state)
        await _emit(db, ws, session.id, "error", {"code": "NOT_FOUND", "message": "报告解读能力将在 M4 接入，当前请先到评测报告页查看。"}, state=state)
        return

    # chat 或未知意图：仅自然语言回复
    await _emit(db, ws, session.id, "thought", {"text": reply or "我可以帮你发起基准评测、生成测试用例等。请描述你的评测目标。"}, state=state)


async def _handle_rule_intent(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    text: str,
    state: _ConnState,
) -> None:
    """规则版意图拆解（LLM 不可用时的降级路径）。"""
    intent = _classify_intent(text)

    if intent == "testcase":
        await _emit(
            db,
            ws,
            session.id,
            "thought",
            {"text": "已识别为 PRD 用例生成目标。将按 6 大策略生成测试用例，生成后需在 72h 内确认入库。请在确认卡中粘贴 PRD / 接口描述文本。"},
            state=state,
        )
        await _send_confirm(
            db,
            ws,
            session.id,
            {"kind": "testcase", "case_source": {"text": ""}},
            state,
        )
        return

    if intent == "rag":
        await _emit(
            db,
            ws,
            session.id,
            "thought",
            {"text": "已识别为 RAG 检索评测目标。知识库与黄金 QA 资产将在 M3 接入，当前请使用「基准评测（Benchmark）」发起评测。"},
            state=state,
        )
        await _emit(
            db,
            ws,
            session.id,
            "error",
            {"code": "NOT_FOUND", "message": "RAG 检索评测能力将在 M3 接入，当前请先使用基准评测。"},
            state=state,
        )
        return

    if intent == "report":
        await _emit(
            db,
            ws,
            session.id,
            "thought",
            {"text": "报告解读能力将在 M4 接入，当前可在「评测报告」页查看已生成报告并做基线对比。"},
            state=state,
        )
        await _emit(
            db,
            ws,
            session.id,
            "error",
            {"code": "NOT_FOUND", "message": "报告解读能力将在 M4 接入，当前请先到评测报告页查看。"},
            state=state,
        )
        return

    # 默认 benchmark：先列出可用协议档与数据集，再生成确认卡
    await _emit(
        db,
        ws,
        session.id,
        "thought",
        {"text": "正在梳理基准评测目标：对比被测协议档在同一数据集上的规则分。先列出可用协议档与数据集…"},
        state=state,
    )
    await _call_tool(db, ws, session.id, "model.list", {}, {"items": _profile_items(db)}, state)
    await _call_tool(db, ws, session.id, "dataset.list", {}, {"items": _dataset_items(db)}, state)

    profiles = _profile_items(db)
    datasets = _dataset_items(db)
    card = {
        "kind": "benchmark",
        "profile_ids": [profiles[0]["id"]] if profiles else [],
        "dataset_id": datasets[0]["id"] if datasets else None,
        "run": _default_run(),
        "with_stress": _wants_stress(text),
        "stress": _default_stress(),
    }
    summary = (
        f"找到 {len(profiles)} 个被测协议档与 {len(datasets)} 个数据集，请确认评测单"
        + ("（已按「先评后压」预开压测开关）" if card["with_stress"] else "")
        + "："
    )
    await _emit(db, ws, session.id, "thought", {"text": summary}, state=state)
    await _send_confirm(db, ws, session.id, card, state)


async def _handle_confirm_ack(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    user: User,
    ok: bool,
    patch: dict | None,
    state: _ConnState,
) -> None:
    """处理确认卡回执：取消则清卡，确认则深合并 patch 后校验并入队。"""
    base = _PENDING_CARDS.get(session.id)

    if not ok:
        _PENDING_CARDS.pop(session.id, None)
        await _emit(db, ws, session.id, "thought", {"text": "已取消本次确认，不会创建任务。需要调整目标可以继续说。"}, state=state)
        return

    if base is None:
        await _emit(db, ws, session.id, "error", {"code": "VALIDATION", "message": "没有待确认的评测单，请先发送目标重新生成。"}, state=state)
        return

    merged = _deep_merge(deepcopy(base), patch or {})

    # 会话内并发约束：同一会话同一时刻最多一个非终态任务
    existing = (
        db.query(Task)
        .filter(Task.session_id == session.id, Task.status.in_(_ACTIVE_STATUSES))
        .first()
    )
    if existing:
        await _emit(db, ws, session.id, "error", {"code": "CONCURRENCY", "message": "当前会话已有未完成任务，请等待其结束后再下单。"}, state=state)
        return

    # 复用与 REST 相同的 TaskCreate 校验（PRD 确认卡字段规则）
    try:
        spec = TaskCreate.model_validate(merged)
    except Exception:
        await _emit(db, ws, session.id, "error", {"code": "VALIDATION", "message": "评测单字段不完整或非法，请补全后重新确认。"}, state=state)
        return

    task = Task(
        kind=spec.kind,
        session_id=session.id,
        config=spec.snapshot(),
        progress={"done": 0, "total": 0, "message": "任务已入队"},
        created_by=user.id,
        status="queued",
    )
    db.add(task)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_create",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
        )
    )
    db.commit()
    db.refresh(task)

    _PENDING_CARDS.pop(session.id, None)

    await _emit(db, ws, session.id, "tool_call", {"name": "task.create", "arguments": spec.snapshot()}, task_id=task.id, state=state)
    await _emit(
        db,
        ws,
        session.id,
        "tool_result",
        {"name": "task.create", "ok": True, "data": {"task_id": task.id, "status": "queued"}},
        task_id=task.id,
        state=state,
    )
    await _emit(db, ws, session.id, "thought", {"text": "任务已入队（queued），Worker 将异步执行并回推进度与报告。"}, task_id=task.id, state=state)
    await _emit(
        db,
        ws,
        session.id,
        "progress",
        {"percent": 0, "done": 0, "total": 1, "message": "任务已入队，等待 Worker 领取"},
        task_id=task.id,
        state=state,
    )


async def _handle_cancel_task(
    db: Session,
    ws: WebSocket,
    session: AgentSession,
    user: User,
    task_id: str,
    state: _ConnState,
) -> None:
    """取消当前成员的非终态任务，与 REST cancel 语义一致。"""
    task = db.query(Task).filter(Task.id == task_id, Task.created_by == user.id).first()
    if not task:
        await _emit(db, ws, session.id, "error", {"code": "NOT_FOUND", "message": "任务不存在"}, state=state)
        return
    if task.status in _TERMINAL_STATUSES:
        await _emit(db, ws, session.id, "error", {"code": "VALIDATION", "message": "任务已结束"}, task_id=task.id, state=state)
        return
    task.cancel_requested_at = datetime.now(UTC)
    task.status = "cancelled"
    task.finished_at = task.cancel_requested_at
    task.progress = {**(task.progress or {}), "message": "任务已取消"}
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_cancel",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
        )
    )
    db.commit()
    await _emit(db, ws, session.id, "thought", {"text": "已收到取消请求，任务状态已更新为 cancelled。"}, task_id=task.id, state=state)


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


async def _forward_loop(ws: WebSocket, session_id: str, state: _ConnState) -> None:
    """后台转发循环：把 Worker 等进程外写入 ws_events 的新事件推送到当前连接。

    Worker 执行长任务时只向 ws_events 表追加 progress/report/error 事件，
    本循环按游标增量检出并在连接锁内发送，与 _emit 的直连发送互斥去重。
    连接关闭（发送抛异常）时静默退出，由主循环的 finally 统一清理。
    """
    while True:
        await asyncio.sleep(1.0)
        db: Session = SessionLocal()
        try:
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
        else:
            await _emit(
                db,
                websocket,
                session_id,
                "thought",
                {"text": "你好，我是评测工程师助手。请描述评测目标，我会澄清后给你确认卡。"},
                state=state,
            )

        # 启动后台转发：Worker 回推的 progress/report/error 经 ws_events 表送达本连接
        forwarder = asyncio.create_task(_forward_loop(websocket, session_id, state))
        # 启动应用层心跳：周期发送 pong 供前端判活（前端不发 JSON ping）
        heartbeat = asyncio.create_task(
            _heartbeat_loop(websocket, session_id, state, _heartbeat_interval(db))
        )

        while True:
            raw = await websocket.receive_text()
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
                if not isinstance(attachments, list):
                    await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "attachments 格式无效"}, state=state)
                    continue
                if not text and not attachments:
                    await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "消息不能为空"}, state=state)
                    continue
                try:
                    await _handle_user_message(db, websocket, session, text, attachments, state)
                except ValueError as exc:
                    await _emit(db, websocket, session_id, "error", {"code": "NOT_FOUND", "message": str(exc)}, state=state)
                continue

            if event == "confirm_ack":
                ok = bool(payload.get("ok"))
                patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else None
                await _handle_confirm_ack(db, websocket, session, user, ok, patch, state)
                continue

            if event == "cancel_task":
                task_id = str(payload.get("task_id", ""))
                await _handle_cancel_task(db, websocket, session, user, task_id, state)
                continue

            await _emit(db, websocket, session_id, "error", {"code": "VALIDATION", "message": "不支持的消息类型"}, state=state)
    except WebSocketDisconnect:
        pass
    finally:
        if forwarder is not None:
            forwarder.cancel()
        if heartbeat is not None:
            heartbeat.cancel()
        db.close()
