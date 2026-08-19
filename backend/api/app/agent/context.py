"""模型窗口与 /compact 算法（开发说明书 §16.6）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from ..models import Message
from ..models import Session as AgentSession
from .defaults import COMPACT_INPUT_MAX, KEEP_RECENT, SUMMARY_MAX_CHARS, WINDOW
from .log import agent_trace
from .persona import COMPACT_SYSTEM


@dataclass(frozen=True)
class ContextMeter:
    """ContextMeter 四段数字（/20 只约束消息窗口）。"""

    messages: int
    skills: int
    summary: int
    headroom: int
    window: int = WINDOW

    def as_dict(self) -> dict:
        return {
            "messages": self.messages,
            "skills": self.skills,
            "summary": self.summary,
            "headroom": self.headroom,
            "window": self.window,
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


def context_meter(db: Session, session: AgentSession, *, skill_id: str | None = None) -> ContextMeter:
    """刷新用的四段计数；技能仅在本轮规划进行中为 1。"""
    rows = window_rows(db, session)
    m_count = len(rows)
    summary_flag = 1 if getattr(session, "compact_summary", None) else 0
    skill_flag = 1 if skill_id else 0
    return ContextMeter(
        messages=m_count,
        skills=skill_flag,
        summary=summary_flag,
        headroom=WINDOW - m_count,
    )


def history_for_plan(db: Session, session: AgentSession) -> list[dict[str, str]]:
    """规划调用的 history：窗口内 role+content，不含 progress。"""
    return [{"role": row.role, "content": row.content or ""} for row in window_rows(db, session)]


def run_compact(db: Session, session: AgentSession) -> tuple[str, int, int]:
    """执行手动 /compact。

    返回 (交付句, old_M, new_M)。上下文较短时不调模型、不改列。
    失败不改两列，向上抛 AppError。
    """
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

    summary = (result.text or "").strip()[:SUMMARY_MAX_CHARS]
    if not summary:
        raise AppError(ErrorCode.UPSTREAM, "上下文压缩失败，窗口未改动")
    session.compact_summary = summary
    session.compact_keep_from = keep[0].id
    db.commit()
    new_m = len(keep)
    agent_trace(f"compact 完成 old_m={old_m} new_m={new_m}")
    return f"已压缩 {old_m}→{new_m}", old_m, new_m
