"""Agent 会话「待处理卡」持久化层（自 ``ws.py`` 抽出）。

承载三类交互卡（任务确认 / 工具审批 / 澄清问答）共用的
``sessions.pending_confirm`` 单行落库、清理与恢复，以及卡元数据（H5 恢复协议）
与审批卡 TTL 判定。本模块只依赖 ORM 与纯函数，不持有连接状态、不参与事件发射，
可脱离 ws 连接生命周期独立测试。

``ws.py`` 以同名符号 re-export 本模块成员，既有调用点与测试引用保持不变。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..agent.log import agent_trace
from ..config import settings
from ..errors import AppError, ErrorCode
from ..models import Session as AgentSession
from ..models import User


def _confirm_author_payload(db: Session, user_id: str | None) -> dict[str, str] | None:
    """确认卡作者元数据；不进卡标 JSON，仅供前端展示与 pending_confirm_author_id。"""
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.id:
        return None
    return {
        "id": str(user.id),
        "username": str(user.username or ""),
        "display_name": str(user.display_name or user.username or ""),
    }


# #1（V1.72）：三类卡共用 pending_confirm 单行，meta 卡种枚举扩展 clarify——
# schema_version 1 → 2 标识卡元数据结构升版；消费端（W5 confirm_ack /
# H5 tool_approval_ack）均不读 schema 数字分支，升版对既有路径零影响。
_CONFIRM_SCHEMA_VERSION = 2

# #3 审批终态：TTL 失效判定辅助（幂等，不依赖扫描进程存活性，API.md §4.3 V1.73）


def _card_age_seconds(card: Mapping[str, Any] | None) -> float | None:
    """解析卡 meta.created_at（UTC ISO）相对当前时间的年龄秒数。

    卡无 meta / created_at 缺失或不可解析时返回 None（调用方按不判龄处理——
    旧版无时间戳卡保持原语义，由扫描或重启后自然消费/清理）。
    """
    if not isinstance(card, Mapping):
        return None
    meta = card.get("meta")
    if not isinstance(meta, Mapping):
        return None
    raw = meta.get("created_at")
    try:
        parsed = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - parsed).total_seconds()


def _approval_overdue(card: Mapping[str, Any] | None) -> bool:
    """审批卡是否已超 TTL 失效（TTL ≤ 0 表示不启用过期，config 可关）。

    判龄以卡创建时间为锚，任何进程（扫描或 ack 路径）都可独立得出同一结论，
    天然幂等；扫描缺席时 ack 路径仍拒绝过期卡，不会绕过失效语义恢复回合。
    """
    ttl = settings.agent_approval_ttl_seconds
    if ttl <= 0:
        return False
    age = _card_age_seconds(card)
    return age is not None and age > ttl


def _card_meta(
    owner_id: str,
    thread_id: str | None,
    confirm_type: str,
    *,
    resume_nonce: str | None = None,
) -> dict[str, Any]:
    """H5 恢复协议元数据（写入卡 JSONB ``meta`` 键；task 确认/工具审批共用）。

    字段：schema_version / confirm_type / thread_id / owner_id /
    created_at；工具审批卡另带一次性 resume_nonce（恢复图检查点用，
    消费即失效——并发/重复恢复由行锁 + 清卡保证至多一次）。
    """
    meta: dict[str, Any] = {
        "schema_version": _CONFIRM_SCHEMA_VERSION,
        "confirm_type": confirm_type,
        "thread_id": thread_id or "",
        "owner_id": owner_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if resume_nonce:
        meta["resume_nonce"] = resume_nonce
    return meta


def _persist_pending_confirm(
    db: Session,
    session_id: str,
    payload: dict[str, Any],
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """把确认卡 TaskSpec 写入 sessions.pending_confirm（行锁），供 confirm_ack 二次校验。

    ``confirm_author`` 只作归属元数据，不进入卡标 JSON（前端提交 patch 须剥离）。
    H5：卡 JSONB 附 ``meta`` 恢复协议元数据（schema_version/confirm_type/
    thread_id/created_at）；会话已有待处理卡（确认/审批任意种类）→
    CONCURRENCY，绝不覆盖（团队协作不得抢占）。
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
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    if session.pending_confirm is not None:
        raise AppError(ErrorCode.CONCURRENCY, "会话存在待处理任务卡，请先确认或取消")
    owner_id = str(author_id or user_id or session.user_id or "")
    spec["meta"] = _card_meta(
        owner_id, thread_id, "task_confirm", resume_nonce=None
    )
    session.pending_confirm = spec
    session.pending_confirm_author_id = owner_id
    db.commit()


def _persist_pending_approval(
    db: Session,
    session_id: str,
    approval: dict[str, Any],
    *,
    thread_id: str,
    user_id: str,
) -> dict[str, Any]:
    """工具审批卡落库（H5 HITL：图 interrupt 后由 ws 层落卡，等待 resume）。

    卡 JSONB：``meta``（confirm_type=tool_approval + 一次性 resume_nonce）+
    ``approval`` 字段白名单（id/call_id/name/command/reason/risk_level）。
    行锁：已有任何待处理卡 → CONCURRENCY。返回卡 dict（含 meta）。
    """
    session = (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id)
        .with_for_update()
        .first()
    )
    if not session:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    if session.pending_confirm is not None:
        raise AppError(ErrorCode.CONCURRENCY, "会话存在待处理任务卡，请先确认或取消")
    allowed = {"id", "call_id", "name", "command", "reason", "risk_level", "sandbox_scope"}
    card = {
        key: value for key, value in approval.items() if key in allowed
    }
    card["meta"] = _card_meta(
        user_id,
        thread_id,
        "tool_approval",
        resume_nonce=uuid4().hex,
    )
    session.pending_confirm = card
    session.pending_confirm_author_id = user_id
    db.commit()
    return card


def _persist_pending_clarify(
    db: Session,
    session_id: str,
    clarify: dict[str, Any],
    *,
    thread_id: str,
    user_id: str,
) -> dict[str, Any]:
    """澄清卡落库（#1 B 路线：与审批卡共用 ``pending_confirm`` 单行互斥）。

    卡 JSONB：``meta``（confirm_type=clarify + 一次性 resume_nonce）+ 白名单
    字段 ``id`` / ``questions``（questions 为 toolnode 侧 validate_questions
    归一后的 ≤8 题三题型结构，ws 层做轻量 sanity 校验）。行锁：已有任何
    待处理卡 → CONCURRENCY。返回卡 dict（含 meta）。
    """
    session = (
        db.query(AgentSession)
        .filter(AgentSession.id == session_id)
        .with_for_update()
        .first()
    )
    if not session:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    if session.pending_confirm is not None:
        raise AppError(ErrorCode.CONCURRENCY, "会话存在待处理任务卡，请先确认或取消")
    allowed = {"id", "questions"}
    card = {key: value for key, value in clarify.items() if key in allowed}
    questions = card.get("questions")
    if not isinstance(card.get("id"), str) or not card["id"]:
        raise AppError(ErrorCode.VALIDATION, "澄清问题缺少卡标识")
    if not isinstance(questions, list) or not questions or len(questions) > 8:
        raise AppError(ErrorCode.VALIDATION, "澄清问题数量必须为 1–8 个")
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, Mapping):
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个澄清问题格式无效")
        if not isinstance(item.get("id"), str) or not str(item.get("question") or "").strip():
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个澄清问题缺少 id 或 question")
    card["meta"] = _card_meta(
        user_id,
        thread_id,
        "clarify",
        resume_nonce=uuid4().hex,
    )
    session.pending_confirm = card
    session.pending_confirm_author_id = user_id
    db.commit()
    return card


def _clear_pending_confirm(db: Session, session_id: str) -> None:
    """清空待确认卡（与回执同事务提交，避免入队成功而卡标残留）。"""
    db.execute(
        text(
            "UPDATE sessions SET pending_confirm = NULL, pending_confirm_author_id = NULL "
            "WHERE id = :session_id"
        ),
        {"session_id": session_id},
    )


def _restore_pending_confirm(
    db: Session,
    session_id: str,
    task_spec: dict[str, Any],
    user_id: str,
) -> None:
    """在确认重放未入队时恢复待确认卡，且不覆盖可能已生成的新卡。

    回放租约已阻止本进程普通回合并发；额外的 ``IS NULL`` 条件仍为断线恢复或
    多连接边界提供纵深保护。TaskSpec 经同源校验后才会到达此处，序列化为 JSONB
    与 ``pending_confirm`` 的持久化格式保持一致。
    """
    try:
        db.execute(
            text(
                "UPDATE sessions SET pending_confirm = CAST(:pending_confirm AS jsonb), "
                "pending_confirm_author_id = :author_id "
                "WHERE id = :session_id AND pending_confirm IS NULL"
            ),
            {
                "pending_confirm": json.dumps(task_spec, ensure_ascii=False),
                "author_id": user_id,
                "session_id": session_id,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        agent_trace(f"confirm_ack 恢复待确认卡失败 type={type(exc).__name__}")


def _error_code_from_payload(value: object) -> ErrorCode:
    """把图内错误码安全归一为公开 ErrorCode，未知值不透出实现细节。"""
    try:
        return ErrorCode(str(value))
    except ValueError:
        return ErrorCode.INTERNAL
