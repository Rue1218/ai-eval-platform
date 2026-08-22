"""手动 /compact 编排：调用模型生成摘要，再经记忆适配器持久化窗口游标。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.defaults import COMPACT_INPUT_MAX, KEEP_RECENT, SUMMARY_MAX_CHARS, WINDOW
from app.agent.log import agent_trace
from app.agent.persona import COMPACT_SYSTEM
from app.errors import AppError, ErrorCode
from app.harness.memory.session_context_store import SessionContextStore
from app.models import Session as AgentSession


def run_compact(
    db: Session,
    session: AgentSession,
    *,
    stop: object | None = None,
) -> tuple[str, int, int] | None:
    """压缩当前会话窗口；数据库访问只经 SessionContextStore 完成。"""

    def _aborted() -> bool:
        return stop is not None and hasattr(stop, "is_set") and stop.is_set()

    if _aborted():
        return None
    store = SessionContextStore(db)
    rows = store.window_messages(session, max_messages=WINDOW)
    old_message_count = len(rows)
    if old_message_count <= KEEP_RECENT:
        return "上下文较短，无需压缩", old_message_count, old_message_count

    keep = rows[-KEEP_RECENT:]
    summarize_rows = rows[: len(rows) - KEEP_RECENT]
    payload = "\n".join(f"{row.role}: {row.content}" for row in summarize_rows)
    if len(payload) > COMPACT_INPUT_MAX:
        payload = payload[-COMPACT_INPUT_MAX:]
    try:
        from app.llm import call_agent_model_detailed

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
    store.save_compaction(session, summary=summary, keep_from_id=keep[0].id)
    new_message_count = len(keep)
    agent_trace(f"compact 完成 old_m={old_message_count} new_m={new_message_count}")
    return f"已压缩 {old_message_count}→{new_message_count}", old_message_count, new_message_count
