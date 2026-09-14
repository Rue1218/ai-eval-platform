"""Agent WebSocket 消息视图层（自 ``ws.py`` 抽出）。

承载会话消息的对外投影：用户 / 助手消息的展示 payload（与 REST 历史回放同格式），
以及 Harness 上下文窗口投影（CX-1/CX-2：窗口裁剪 + 裁剪元信息留痕）。

本模块只依赖 ORM 与 Harness 上下文算法，不持有连接状态与事件发射逻辑，可独立测试。
``ws.py`` 以同名符号 re-export，既有调用点不变。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..agent.attachments import model_content_for_message
from ..harness.context import window_trim_stats
from ..models import Message, User
from ..models import Session as AgentSession
from ..time_utils import iso_utc


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
        "created_at": iso_utc(row.created_at),
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
        "created_at": iso_utc(row.created_at),
    }


def _window_messages(db: Session, session_id: str) -> tuple[list[dict], dict[str, object]]:
    """读取会话消息，经 Harness 窗口算法（CX-1）投影（含 source_id）。

    ``compact_keep_from`` 指定保留起点时截断更早消息；思考/工具/确认/进度
    事件不进窗口（CX-2）。窗口算法唯一来源为
    ``app.harness.context.window.recent_window``（#2 起经 window_trim_stats
    同源实现返回裁剪元信息，供 context_trim 留痕事件使用）。
    返回 ``(窗口消息, trim_meta)``；trim_meta.dropped>0 即本回合发生了窗口裁剪。
    """
    session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
    # getattr 容错：会话行缺少该列（测试桩/旧快照）时按未压缩处理
    keep_from = getattr(session, "compact_keep_from", None) if session else None
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
            # 附件装配（staging）在 model_content_for_message 内按会话绑定自行
            # 解析（resolve_session_sandbox_db，与 _run_turn 注入同源同态——BLK-1）
            "content": model_content_for_message(db, row) if row.role == "user" else row.content,
            "source_id": row.source_id,
        }
        for row in reversed(rows)
    ]
    return window_trim_stats(ordered, limit=20, keep_from=keep_from)


def _history_with_trim(
    db: Session, session_id: str
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """窗口投影消息 + 裁剪元信息（#2 留痕用，与 _window_messages 同一次查询）。"""
    windowed, meta = _window_messages(db, session_id)
    return [
        {"role": item["role"], "content": item["content"]}
        for item in windowed
    ], meta
