"""Harness 编排层：确认卡回执处理（M4 阶段 4，OR-8）。

``handle_confirm_ack`` 由 ws.py 收包循环**直连**（不唤醒图）：
行锁读 pending_confirm → owner 校验 → 并发检测 → ok=true 则 patch 深合并 →
按 PRD §5.1.2 / API.md §5 二次校验 → task.create（queued + AuditLog）→
清空 pending_confirm；ok=false 不入队、清空卡标。全程同一 DB 事务，单次行锁。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.errors import AppError, ErrorCode
from app.harness.execution.worker_bridge import TASK_KINDS, enqueue_long_task
from app.harness.memory import prefs_from_task_spec, write_prefs
from app.harness.security.auth import (
    assert_confirm_owner,
    assert_no_concurrent_confirm,
    lock_pending_confirm,
)
from app.schemas import TaskCreate


@dataclass(frozen=True, slots=True)
class ConfirmAckResult:
    """回执处理结果（由 ws.py emit confirm_ack/tool_call/tool_result）。"""

    ok: bool
    task_id: str | None = None
    kind: str | None = None
    message: str = "已取消确认"  # ok=false 时提示
    merged: dict = field(default_factory=dict)


def _deep_merge(base: dict, patch: dict) -> dict:
    """深合并确认卡 patch（嵌套 dict 递归合并）。"""
    merged = dict(base)
    for key, value in patch.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


_TASK_SPEC_KEYS = frozenset(
    {
        "kind",
        "session_id",
        "parent_task_id",
        "profile_ids",
        "dataset_id",
        "kb_id",
        "gold_qa_id",
        "rag_mode",
        "run",
        "with_stress",
        "stress",
        "case_source",
    }
)


def _confirm_validation_message(exc: ValidationError) -> str:
    """把 Pydantic 校验错误归一为确认卡中文提示，不把校验器原文甩给浏览器。"""
    texts: list[str] = []
    locs: set[str] = set()
    for err in exc.errors():
        locs.update(str(item) for item in (err.get("loc") or ()))
        ctx = err.get("ctx") or {}
        inner = ctx.get("error")
        if inner:
            texts.append(str(inner))
        texts.append(str(err.get("msg") or ""))
    blob = " ".join(texts)
    if "dataset_id" in locs or "dataset_id" in blob or "数据集" in blob:
        return "确认卡缺少数据集"
    if (
        "kb_id" in locs
        or "gold_qa_id" in locs
        or "kb_id" in blob
        or "gold_qa" in blob
        or "黄金" in blob
    ):
        return "确认卡缺少知识库或黄金 QA"
    if "case_source" in locs or "case_source" in blob:
        return "确认卡缺少用例来源"
    if "profile_ids" in locs or "profile_ids" in blob:
        return "确认卡缺少被测协议档"
    if "run" in locs and "run" in blob:
        return "确认卡缺少运行参数"
    if "stress" in locs or "with_stress" in blob:
        return "勾选先评后压时需要压测参数"
    for text in texts:
        if text and text not in {"Value error", "Field required"}:
            return text.split("Value error, ")[-1]
    return "确认卡字段不完整或非法"


def _validate_confirmed(task_spec: dict) -> str:
    """按 PRD §5.1.2 / API.md §5 二次校验确认卡字段；返回 kind。"""
    kind = task_spec.get("kind")
    if kind == "stress":
        raise AppError(
            ErrorCode.VALIDATION,
            "压测由质量任务勾选「先评后压」派生，不能单独下单",
        )
    if kind not in TASK_KINDS:
        raise AppError(ErrorCode.VALIDATION, f"未知任务类型：{kind}")
    try:
        cleaned = {key: value for key, value in task_spec.items() if key in _TASK_SPEC_KEYS}
        TaskCreate.model_validate(cleaned)
    except ValidationError as exc:
        raise AppError(ErrorCode.VALIDATION, _confirm_validation_message(exc)) from exc
    return str(kind)


def handle_confirm_ack(
    db,
    session_id: str,
    user_id: str,
    payload: dict,
) -> ConfirmAckResult:
    """处理确认卡回执（OR-8，全程同一事务、单次行锁）。

    - ``ok=true``：patch 深合并 → 二次校验 → ``task.create(queued)`` +
      AuditLog → 清空 pending_confirm；
    - ``ok=false``：不入队，清空卡标（卡标已取消）。
    返回 ``ConfirmAckResult``，由 ws.py emit confirm_ack/tool_call/tool_result。
    """
    confirmed = bool(payload.get("ok"))
    patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else {}
    pending = lock_pending_confirm(db, session_id)  # SELECT ... FOR UPDATE
    assert_confirm_owner(pending, user_id)
    assert_no_concurrent_confirm(pending)
    base = dict(pending.pending or {})
    task_spec = _deep_merge(base, patch)
    try:
        if confirmed:
            kind = _validate_confirmed(task_spec)
            spec = {
                key: value
                for key, value in task_spec.items()
                if key in _TASK_SPEC_KEYS and key != "kind"
            }
            try:
                task_id = enqueue_long_task(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    kind=kind,
                    spec=spec,
                    commit=False,
                )
            except IntegrityError:
                db.rollback()
                raise AppError(ErrorCode.CONCURRENCY, "会话已有未完成任务") from None
        else:
            task_id = None
            kind = task_spec.get("kind")
        # 清空确认卡（无论 ok 与否，卡标已消费）；与入队同一次 commit，避免半提交。
        db.execute(
            __import__("sqlalchemy").text(
                "UPDATE sessions SET pending_confirm = NULL, pending_confirm_author_id = NULL "
                "WHERE id = :session_id"
            ),
            {"session_id": session_id},
        )
        db.commit()
    except AppError:
        db.rollback()
        raise
    if confirmed and task_id:
        # 入队成功后写偏好；失败不影响已入队任务（闲聊/取消不写）。
        try:
            write_prefs(db, user_id, prefs_from_task_spec(task_spec))
        except AppError:
            raise
        except Exception as exc:
            db.rollback()
            from app.agent.log import agent_trace

            agent_trace(f"写偏好失败 type={type(exc).__name__}")
    return ConfirmAckResult(
        ok=confirmed,
        task_id=task_id,
        kind=str(kind) if kind else None,
        message="已确认并入队" if confirmed else "已取消确认",
        merged=task_spec,
    )
