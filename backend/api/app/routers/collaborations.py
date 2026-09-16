"""专家协作只读投影与前端停止入口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AgentCollaboration, AgentInstance, AgentRun, AgentRunEvent, User, utcnow
from ..session_access import require_visible_session

router = APIRouter(prefix="/api", tags=["agent-collaborations"])


class CancelRequest(BaseModel):
    """用户停止原因只用于结构化回执，不进入模型系统提示词。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)] = "用户停止"


def _iso(value) -> str | None:
    """统一投影带时区时间。"""
    return value.isoformat() if value is not None else None


def _require_collaboration(db: DbSession, collaboration_id: str, user: User):
    """协作沿用父会话可见性；停止动作再单独要求创建者。"""
    collaboration = db.get(AgentCollaboration, collaboration_id)
    if collaboration is None:
        raise AppError(ErrorCode.NOT_FOUND, "专家协作不存在")
    session = require_visible_session(db, collaboration.session_id, user.id)
    return collaboration, session


def _run_payload(run: AgentRun, instance: AgentInstance, *, result: bool = True) -> dict:
    """前端安全投影不包含提示词、凭据或完整模型历史。"""
    payload = {
        "run_id": run.id,
        "instance_id": instance.id,
        "expert": instance.expert_snapshot,
        "model": instance.profile_snapshot.get("model"),
        "goal": run.goal,
        "output_contract": run.output_contract,
        "status": run.status,
        "error_code": run.error_code,
        "result_available": run.status in {"succeeded", "failed", "cancelled"},
        "cancel_requested": run.cancel_requested,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }
    if result:
        payload["result"] = run.result
    return payload


def _safe_event(event: dict) -> dict:
    """运行记录只展示事实摘要；原始思考、协议状态、请求头和完整工具观察不出接口。"""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    keys = (
        "turn", "step", "attempt_id", "call_id", "name", "status", "error_code",
        "finish_reason", "reason", "usage",
    )
    summary = {key: data[key] for key in keys if key in data}
    kind = str(event.get("type", ""))
    if kind == "user/message":
        content = data.get("content")
        if isinstance(content, str):
            summary["content"] = content[:4000]
    elif kind == "assistant/message":
        content = data.get("content")
        if not isinstance(content, str) and isinstance(data.get("message"), dict):
            content = data["message"].get("content")
        if isinstance(content, str):
            summary["content"] = content[:4000]
    elif kind == "tool/result":
        content = data.get("content")
        if isinstance(content, str):
            summary["content_preview"] = content[:1000]
    return {
        "seq": event.get("seq"),
        "ts": event.get("ts"),
        "type": kind,
        "run_id": event.get("run_id"),
        "data": summary,
    }


@router.get("/sessions/{session_id}/collaborations")
def list_collaborations(
    session_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: DbSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """按新到旧列出会话协作，重连后页面从这里恢复。"""
    require_visible_session(db, session_id, user.id)
    rows = list(db.execute(select(AgentCollaboration).where(
        AgentCollaboration.session_id == session_id
    ).order_by(AgentCollaboration.created_at.desc()).limit(limit)).scalars())
    return {"items": [{
        "id": row.id,
        "session_id": row.session_id,
        "root_turn": row.root_turn,
        "status": row.status,
        "goal": row.goal,
        "budget": row.budget,
        "cancel_requested": row.cancel_requested,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "finished_at": _iso(row.finished_at),
    } for row in rows]}


@router.get("/collaborations/{collaboration_id}")
def get_collaboration(
    collaboration_id: str,
    db: DbSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """返回协作状态和实例列表，供折叠面板轮询。"""
    collaboration, _session = _require_collaboration(db, collaboration_id, user)
    rows = db.execute(select(AgentRun, AgentInstance).join(
        AgentInstance, AgentInstance.id == AgentRun.instance_id
    ).where(AgentRun.collaboration_id == collaboration.id).order_by(AgentRun.created_at)).all()
    return {
        "id": collaboration.id,
        "session_id": collaboration.session_id,
        "root_turn": collaboration.root_turn,
        "status": collaboration.status,
        "goal": collaboration.goal,
        "budget": collaboration.budget,
        "cancel_requested": collaboration.cancel_requested,
        "created_at": _iso(collaboration.created_at),
        "updated_at": _iso(collaboration.updated_at),
        "finished_at": _iso(collaboration.finished_at),
        "runs": [_run_payload(run, instance) for run, instance in rows],
    }


@router.get("/agent-runs/{run_id}/events")
def list_run_events(
    run_id: str,
    after_seq: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=500),
    db: DbSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """按运行分页查看事实记录；正文只返回已持久的安全事件结构。"""
    run = db.get(AgentRun, run_id)
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, "专家运行不存在")
    _require_collaboration(db, run.collaboration_id, user)
    events = list(db.execute(select(AgentRunEvent.envelope).where(
        AgentRunEvent.run_id == run_id,
        AgentRunEvent.seq > after_seq,
    ).order_by(AgentRunEvent.seq).limit(limit)).scalars())
    return {
        "items": [_safe_event(event) for event in events],
        "next_seq": events[-1]["seq"] if events else after_seq,
    }


def _local_coordinator(request: Request, session_id: str, collaboration_id: str):
    """单副本 P1 从会话运行时定位当前协调器；无本地运行时由数据库终止兜底。"""
    service = getattr(request.app.state, "loop_service", None)
    entry = service.entries.get(session_id) if service is not None else None
    coordinator = getattr(entry, "collaboration_coordinator", None)
    if coordinator is not None and coordinator.collaboration_id == collaboration_id:
        return coordinator
    return None


@router.post("/collaborations/{collaboration_id}/cancel")
async def cancel_collaboration(
    collaboration_id: str,
    payload: CancelRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """停止整组专家；仅父会话创建者拥有控制权。"""
    collaboration, session = _require_collaboration(db, collaboration_id, user)
    if session.user_id != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "只有会话创建者可以停止专家协作")
    if collaboration.status in {"succeeded", "failed", "cancelled"}:
        return {"collaboration_id": collaboration.id, "accepted": False,
                "run_ids": [], "reason": payload.reason}
    coordinator = _local_coordinator(request, collaboration.session_id, collaboration.id)
    if coordinator is not None:
        return await coordinator.cancel_all_by_user(payload.reason)
    collaboration.cancel_requested = True
    collaboration.status = "cancelled"
    collaboration.finished_at = utcnow()
    runs = list(db.execute(select(AgentRun).where(
        AgentRun.collaboration_id == collaboration.id,
        AgentRun.status.in_(("queued", "running")),
    )).scalars())
    for run in runs:
        run.cancel_requested = True
        run.status = "cancelled"
        run.finished_at = utcnow()
    db.commit()
    return {"collaboration_id": collaboration.id, "accepted": bool(runs),
            "run_ids": [run.id for run in runs], "reason": payload.reason}


@router.post("/agent-runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    payload: CancelRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """停止单个专家；重连或进程恢复后仍能看到取消终态。"""
    run = db.get(AgentRun, run_id)
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, "专家运行不存在")
    collaboration, session = _require_collaboration(db, run.collaboration_id, user)
    if session.user_id != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "只有会话创建者可以停止专家")
    coordinator = _local_coordinator(request, collaboration.session_id, collaboration.id)
    if coordinator is not None:
        return await coordinator.cancel_run_by_user(run_id, payload.reason)
    accepted = run.status not in {"succeeded", "failed", "cancelled"}
    if accepted:
        run.cancel_requested = True
        run.status = "cancelled"
        run.error_code = "cancelled"
        run.result = {"content": "", "finish_reason": "cancelled", "complete": False}
        run.finished_at = utcnow()
        # 无本地运行时的恢复路径也要汇总整组，避免最后一个专家已停止但协作仍运行。
        db.flush()
        active = db.execute(select(AgentRun.id).where(
            AgentRun.collaboration_id == collaboration.id,
            AgentRun.status.in_(("queued", "running")),
        ).limit(1)).first()
        if active is None:
            collaboration.status = "cancelled"
            collaboration.finished_at = utcnow()
        db.commit()
    return {"run_id": run_id, "accepted": accepted, "reason": payload.reason}
