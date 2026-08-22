"""模型窗口与 /compact 算法（开发说明书 §16.6）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import settings
from ..errors import AppError, ErrorCode
from ..harness.context.compiler import compile_context
from ..harness.contracts.memory import MemoryQuery
from ..harness.contracts.trace import TraceContext
from ..harness.memory.runtime import memory_port_for_session
from ..models import Message, WsEvent
from ..models import Session as AgentSession
from .defaults import COMPACT_INPUT_MAX, KEEP_RECENT, SUMMARY_MAX_CHARS, WINDOW
from .log import agent_trace
from .persona import COMPACT_SYSTEM


@dataclass(frozen=True)
class ContextMeter:
    """ContextMeter 扩展度量（包含消息窗口与 Token 级容量统计）。"""

    messages: int
    skills: int
    summary: int
    headroom: int
    window: int = WINDOW
    # Token 级绝对值与占比扩展
    total_tokens: int = 0
    max_tokens: int = 200000
    messages_tokens: int = 0
    skills_tokens: int = 0
    free_tokens: int = 200000
    used_percent: float = 0.0
    messages_percent: float = 0.0
    skills_percent: float = 0.0
    free_percent: float = 100.0
    mcp_tools_count: int = 0
    mcp_tools_max: int = 28
    memory_files_count: int = 0
    memory_files_max: int = 1

    def as_dict(self) -> dict:
        return {
            "messages": self.messages,
            "skills": self.skills,
            "summary": self.summary,
            "headroom": self.headroom,
            "window": self.window,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "messages_tokens": self.messages_tokens,
            "skills_tokens": self.skills_tokens,
            "free_tokens": self.free_tokens,
            "used_percent": self.used_percent,
            "messages_percent": self.messages_percent,
            "skills_percent": self.skills_percent,
            "free_percent": self.free_percent,
            "mcp_tools_count": self.mcp_tools_count,
            "mcp_tools_max": self.mcp_tools_max,
            "memory_files_count": self.memory_files_count,
            "memory_files_max": self.memory_files_max,
        }


def _ordered_messages(db: Session, session_id: str) -> list[Message]:
    """按 (created_at, id) 升序取出 user/assistant 原文。"""
    return (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.role.in_(("user", "assistant")))
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )


def window_rows(db: Session, session: AgentSession) -> list[Message]:
    """计算当前模型窗口原文（唯一的 M 定义）。"""
    rows = _ordered_messages(db, session.id)
    keep_from = getattr(session, "compact_keep_from", None)
    if keep_from:
        hit_idx = next((i for i, row in enumerate(rows) if row.id == keep_from), None)
        if hit_idx is not None:
            rows = rows[hit_idx:]
    if len(rows) > WINDOW:
        rows = rows[-WINDOW:]
    return rows


def _persisted_capability_stats(db: Session, session_id: str) -> tuple[bool, int]:
    """从已落库事件恢复技能与短 MCP 工具占用，避免刷新后仪表归零。

    思考增量不会写入事件表，但阶段思考、技能标识和 tool_call/tool_result
    都是可回放事件；这里仅统计唯一工具名，避免同一轮重复调用把数量夸大。
    旧数据库或测试桩没有事件查询能力时安全回退为零。
    """
    try:
        events = (
            db.query(WsEvent)
            .filter(WsEvent.session_id == session_id)
            .order_by(WsEvent.event_id.asc())
            .all()
        )
    except Exception:
        return False, 0
    skill_seen = False
    tool_names: set[str] = set()
    for row in events:
        payload = row.payload if isinstance(row.payload, dict) else {}
        if payload.get("skill_id"):
            skill_seen = True
        if row.event == "tool_call" and payload.get("name"):
            tool_names.add(str(payload["name"]))
    return skill_seen, min(len(tool_names), 28)


def context_meter(db: Session, session: AgentSession, *, skill_id: str | None = None) -> ContextMeter:
    """刷新用的四段计数与 Token 级容量度量。"""
    rows = window_rows(db, session)
    m_count = len(rows)
    summary_flag = 1 if getattr(session, "compact_summary", None) else 0
    persisted_skill, mcp_tools_count = _persisted_capability_stats(db, session.id)
    skill_flag = 1 if skill_id or persisted_skill else 0

    # 1. 尝试从 Profile 读取上下文窗口上限（默认 200,000）
    max_tokens = 200000
    try:
        from ..models import ProtocolProfile, Setting
        setting = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
        if setting and setting.value:
            prof = db.query(ProtocolProfile).filter(ProtocolProfile.id == setting.value).first()
            if prof and getattr(prof, "context_window", None):
                max_tokens = int(prof.context_window)
    except Exception:
        max_tokens = 200000

    # 2. 计算 Token 消耗预估（中英混排约 1.3 字符/Token，加单条消息基础结构开销）
    msg_char_count = sum(len(r.content or "") for r in rows)
    messages_tokens = max(0, int(msg_char_count * 1.35)) + (m_count * 80)
    skills_tokens = 2000 if skill_flag else 0
    summary_tokens = 1200 if summary_flag else 0
    total_tokens = messages_tokens + skills_tokens + summary_tokens

    free_tokens = max(0, max_tokens - total_tokens)
    used_pct = round(min(100.0, (total_tokens / max_tokens) * 100), 1)
    msg_pct = round(min(100.0, (messages_tokens / max_tokens) * 100), 1)
    sk_pct = round(min(100.0, (skills_tokens / max_tokens) * 100), 1) if skill_flag else 0.0
    free_pct = round(max(0.0, 100.0 - used_pct), 1)

    return ContextMeter(
        messages=m_count,
        skills=skill_flag,
        summary=summary_flag,
        headroom=WINDOW - m_count,
        total_tokens=total_tokens,
        max_tokens=max_tokens,
        messages_tokens=messages_tokens,
        skills_tokens=skills_tokens,
        free_tokens=free_tokens,
        used_percent=used_pct,
        messages_percent=msg_pct,
        skills_percent=sk_pct,
        free_percent=free_pct,
        mcp_tools_count=mcp_tools_count,
        mcp_tools_max=28,
        memory_files_count=0,
        memory_files_max=1,
    )


async def history_for_plan(
    db: Session,
    session: AgentSession,
    *,
    trace: TraceContext,
) -> list[dict[str, str]]:
    """规划调用的 history：经 MemoryPort 编译后保留 user/assistant 角色，不含 progress。"""
    query = MemoryQuery(
        query_text="plan-history",
        tenant_id=settings.memory_tenant_id,
        user_id=session.user_id,
        session_id=session.id,
        record_types=["conversation"],
        top_k_recall=WINDOW,
        trace_id=trace.trace_id,
    )
    compiled = await compile_context(
        port=memory_port_for_session(db),
        query=query,
        trace=trace.child("context_retrieve"),
        system_prompt="",
        user_input="",
    )
    return [
        {"role": message["role"], "content": message["content"]}
        for message in compiled.messages
        if message["role"] in {"user", "assistant"}
    ]


def run_compact(
    db: Session,
    session: AgentSession,
    *,
    stop: object | None = None,
) -> tuple[str, int, int] | None:
    """执行手动 /compact。

    返回 (交付句, old_M, new_M)。上下文较短时不调模型、不改列。
    失败不改两列，向上抛 AppError。
    ``stop`` 若已置位（如 /stop、墙钟），不写入两列，返回 None。
    """
    def _aborted() -> bool:
        return stop is not None and hasattr(stop, "is_set") and stop.is_set()

    if _aborted():
        return None
    rows = window_rows(db, session)
    old_m = len(rows)
    if old_m <= KEEP_RECENT:
        return "上下文较短，无需压缩", old_m, old_m

    keep = rows[-KEEP_RECENT:]
    to_summarize = rows[: len(rows) - KEEP_RECENT]
    chunks = [f"{row.role}: {row.content}" for row in to_summarize]
    payload = "\n".join(chunks)
    if len(payload) > COMPACT_INPUT_MAX:
        payload = payload[-COMPACT_INPUT_MAX:]
    try:
        from ..llm import call_agent_model_detailed

        result = call_agent_model_detailed(
            db,
            COMPACT_SYSTEM,
            payload,
            temperature=0.2,
            max_tokens=1024,
        )
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"compact 内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "上下文压缩失败，窗口未改动") from exc

    if _aborted():
        agent_trace("compact 已中止，窗口未改动")
        return None
    summary = (result.text or "").strip()[:SUMMARY_MAX_CHARS]
    if not summary:
        raise AppError(ErrorCode.UPSTREAM, "上下文压缩失败，窗口未改动")
    session.compact_summary = summary
    session.compact_keep_from = keep[0].id
    db.commit()
    new_m = len(keep)
    agent_trace(f"compact 完成 old_m={old_m} new_m={new_m}")
    return f"已压缩 {old_m}→{new_m}", old_m, new_m
