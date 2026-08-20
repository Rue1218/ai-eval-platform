"""短 MCP 工具实现，与清单同源（HAR-NFR-07 / §16.3）。

长工具由 ``long_tasks.assert_short_tool`` 拒绝。``task.create`` 只允许 ack 后调用。
写入 ``tool_result.payload.data`` 的必须是截断、脱敏后的版本。
"""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from ..models import (
    AuditLog,
    CaseSet,
    Dataset,
    DispatchWorker,
    ProtocolProfile,
    Report,
    Task,
    TaskEvent,
)
from .defaults import (
    ACTIVE_STATUSES,
    IMPLEMENTED_SHORT_TOOLS,
    LIST_SUMMARY_LIMIT,
    OBSERVATION_JSON_MAX,
    SHORT_TOOLS,
    TERMINAL_STATUSES,
    TOOL_TITLES,
)
from .log import agent_trace
from .long_tasks import assert_short_tool

_SENSITIVE_KEY_RE = re.compile(r"(?i)(api_key|token|password|secret|cookie)")

# 尚未按里程碑交付的短工具：观察记失败，禁止假成功（知识库表属 M3）
_UNIMPLEMENTED_TOOLS = SHORT_TOOLS - IMPLEMENTED_SHORT_TOOLS


def redact_secrets(value: Any) -> Any:
    """键名匹配敏感模式时值替换为 ``***``。"""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key):
                out[key] = "***"
            else:
                out[key] = redact_secrets(item)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def truncate_tool_data(data: Any) -> Any:
    """list 最多 20 条；整段 JSON 超过 4000 字符则截断并标记 truncated。"""
    payload = redact_secrets(deepcopy(data) if not isinstance(data, str) else data)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
        if len(items) > LIST_SUMMARY_LIMIT:
            payload = dict(payload)
            payload["items"] = items[:LIST_SUMMARY_LIMIT]
            payload["truncated"] = True
    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        raw = str(payload)
    if len(raw) > OBSERVATION_JSON_MAX:
        return {"truncated": True, "preview": raw[:OBSERVATION_JSON_MAX]}
    return payload


def collect_ids(data: Any) -> list[str]:
    """从工具返回中收集资产 ID，供复核 G3 溯源。"""
    ids: list[str] = []
    if isinstance(data, dict):
        if isinstance(data.get("id"), str) and data["id"]:
            ids.append(data["id"])
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                    ids.append(item["id"])
        for key in ("task_id", "report_id", "dataset_id", "kb_id", "gold_qa_id", "case_set_id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                ids.append(value)
    return ids


def summarize_observation(name: str, ok: bool, data: Any, error: str | None, latency_ms: int) -> dict:
    """构造 ReactArtifact.observations 条目。"""
    ids = collect_ids(data) if ok else []
    summary: dict[str, Any] = {"ids": ids[:LIST_SUMMARY_LIMIT]}
    if ok and isinstance(data, dict):
        for key in ("id", "task_id", "report_id", "case_set_id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                summary[key] = value
        if isinstance(data.get("items"), list):
            summary["count"] = len(data["items"])
            names = [
                item.get("name")
                for item in data["items"][:LIST_SUMMARY_LIMIT]
                if isinstance(item, dict) and item.get("name")
            ]
            if names:
                summary["names"] = names
    if not ok and error:
        summary["error"] = error
    return {
        "name": name,
        "ok": ok,
        "latency_ms": latency_ms,
        "data_summary": summary,
    }


def _list_profiles(db: Session) -> dict:
    rows = db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.desc()).all()
    return {
        "items": [
            {"id": p.id, "name": p.name, "protocol": p.protocol, "model": p.model}
            for p in rows
        ]
    }


def _list_datasets(db: Session) -> dict:
    rows = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
    return {
        "items": [
            {
                "id": d.id,
                "name": d.name,
                "version": d.version,
                "row_count": d.row_count,
                "metric": d.metric,
            }
            for d in rows
        ]
    }


def _task_get(db: Session, arguments: dict, user_id: str) -> dict:
    task_id = str(arguments.get("task_id") or "")
    query = db.query(Task)
    if task_id:
        task = query.filter(Task.id == task_id).first()
    else:
        task = (
            query.filter(Task.created_by == user_id)
            .order_by(Task.created_at.desc())
            .first()
        )
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "progress": task.progress or {},
        "report_id": task.report_id,
    }


def _dispatch_overview(db: Session) -> dict:
    from ..routers.dispatch import HEARTBEAT_INTERVAL_MS, _effective_state, _load_config

    workers = db.query(DispatchWorker).all()
    online = sum(1 for worker in workers if _effective_state(worker) in {"idle", "busy"})
    queue_depth = db.query(Task).filter(Task.status == "queued").count()
    config = _load_config(db)
    return {
        "workers": online,
        "queue_depth": queue_depth,
        "strategy": config["strategy"],
        "total_workers": len(workers),
        "heartbeat_interval_ms": HEARTBEAT_INTERVAL_MS,
    }


def _report_get(db: Session, arguments: dict, user_id: str) -> dict:
    report_id = str(arguments.get("report_id") or "")
    if not report_id:
        # ReAct 常先 task.get；未带 id 时取当前成员最近一份带报告的任务
        task = (
            db.query(Task)
            .filter(Task.created_by == user_id, Task.report_id.isnot(None))
            .order_by(Task.created_at.desc())
            .first()
        )
        report_id = str(task.report_id) if task and task.report_id else ""
    if not report_id:
        raise AppError(ErrorCode.VALIDATION, "report_id 必填")
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在")
    return {
        "report_id": report.id,
        "summary": (report.metrics or {}).get("summary") if isinstance(report.metrics, dict) else None,
        "download_url": f"/api/reports/{report.id}?fmt=md",
    }


def cancel_owned_task(
    db: Session,
    *,
    task_id: str,
    user_id: str,
    session_id: str | None = None,
    reason: str | None = None,
) -> dict:
    """取消当前成员的非终态任务；与 REST / WS 取消同一套权限与终态规则。"""
    _ = reason
    query = db.query(Task)
    if task_id:
        task = query.filter(Task.id == task_id).with_for_update().first()
    else:
        scoped = query.filter(Task.created_by == user_id, Task.status.in_(tuple(ACTIVE_STATUSES)))
        if session_id:
            scoped = scoped.filter(Task.session_id == session_id)
        task = scoped.order_by(Task.created_at.desc()).with_for_update().first()
    if not task:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    if task.created_by != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事", status_code=401)
    if session_id and task.session_id and task.session_id != session_id:
        raise AppError(ErrorCode.VALIDATION, "只能取消当前会话中的任务")
    if task.status in TERMINAL_STATUSES:
        raise AppError(ErrorCode.VALIDATION, "任务已结束")
    now = datetime.now(UTC)
    task.cancel_requested_at = now
    task.status = "cancelled"
    task.finished_at = now
    task.progress = {**(task.progress or {}), "message": "任务已取消"}
    db.add(
        TaskEvent(
            task_id=task.id,
            event="cancelled",
            message="任务已取消",
            payload={"status": "cancelled"},
        )
    )
    db.add(
        AuditLog(
            user_id=user_id,
            action="task_cancel",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
        )
    )
    return {"ok": True, "task_id": task.id, "status": "cancelled"}


def _testcase_confirm(db: Session, arguments: dict, user_id: str) -> dict:
    """确认或废弃用例集，并联动 awaiting_case_confirm 任务终态。"""
    case_set_id = str(arguments.get("case_set_id") or "").strip()
    if not case_set_id:
        raise AppError(ErrorCode.VALIDATION, "case_set_id 必填")
    ok_raw = arguments.get("ok", True)
    ok = True if ok_raw is True or ok_raw is None else str(ok_raw).lower() not in {"false", "0", "no"}
    case_set = db.query(CaseSet).filter(CaseSet.id == case_set_id).first()
    if not case_set:
        raise AppError(ErrorCode.NOT_FOUND, "用例集不存在")
    if case_set.status in {"confirmed", "cancelled"}:
        raise AppError(ErrorCode.VALIDATION, "用例集已终态，请勿重复操作")
    if ok:
        case_set.status = "confirmed"
        case_set.confirmed_count = case_set.generated_count
        task_status = "succeeded"
    else:
        case_set.status = "cancelled"
        task_status = "cancelled"
    if case_set.task_id:
        task = db.query(Task).filter(Task.id == case_set.task_id).first()
        if task and task.status == "awaiting_case_confirm":
            task.status = task_status
            task.finished_at = datetime.now(UTC)
    db.add(
        AuditLog(
            user_id=user_id,
            action="case_set_confirm",
            target_type="case_set",
            target_id=case_set.id,
            detail={
                "name": case_set.name,
                "ok": ok,
                "edits": arguments.get("edits"),
            },
        )
    )
    return {
        "status": "succeeded" if ok else "cancelled",
        "case_set_id": case_set.id,
        "case_set_status": case_set.status,
    }


def execute_short_tool(
    db: Session,
    name: str,
    arguments: dict | None,
    *,
    user_id: str,
    allow_create: bool = False,
    session_id: str | None = None,
) -> tuple[bool, Any, str | None, int]:
    """执行一个短工具，返回 (ok, data, error, latency_ms)。

    ``task.create`` 仅当 ``allow_create=True``（ack 后）才执行。
    ``session_id`` 用于 ``task.cancel`` 限制只能动当前会话任务。
    """
    started = time.perf_counter()
    args = arguments if isinstance(arguments, dict) else {}
    try:
        assert_short_tool(name)
        if name not in SHORT_TOOLS:
            raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")
        if name == "task.create" and not allow_create:
            raise AppError(ErrorCode.VALIDATION, "task.create 只允许在确认卡 ack 之后执行")
        if name in _UNIMPLEMENTED_TOOLS:
            raise AppError(ErrorCode.VALIDATION, "该能力未启用")

        if name == "model.list":
            data: Any = _list_profiles(db)
        elif name == "dataset.list":
            data = _list_datasets(db)
        elif name == "task.get":
            data = _task_get(db, args, user_id)
        elif name == "dispatch.overview":
            data = _dispatch_overview(db)
        elif name == "report.get":
            data = _report_get(db, args, user_id)
        elif name == "task.cancel":
            data = cancel_owned_task(
                db,
                task_id=str(args.get("task_id") or ""),
                user_id=user_id,
                session_id=session_id,
                reason=str(args["reason"]) if args.get("reason") else None,
            )
        elif name == "testcase.confirm":
            data = _testcase_confirm(db, args, user_id)
        else:
            raise AppError(ErrorCode.VALIDATION, "该能力未启用")

        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_trace(f"短工具完成 name={name} latency={latency_ms}ms")
        return True, truncate_tool_data(data), None, latency_ms
    except AppError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_trace(f"短工具失败 name={name} code={exc.code.value} latency={latency_ms}ms")
        return False, None, exc.message, latency_ms
    except Exception as exc:
        agent_trace(f"短工具内部异常 name={name} type={type(exc).__name__}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        return False, None, "操作失败", latency_ms


def tool_title(name: str) -> str:
    """工具卡中文名。"""
    return TOOL_TITLES.get(name, name)
