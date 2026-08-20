"""短 MCP 工具实现，与清单同源（HAR-NFR-07 / §16.3）。

长工具由 ``long_tasks.assert_short_tool`` 拒绝。``task.create`` 只允许 ack 后调用。
写入 ``tool_result.payload.data`` 的必须是截断、脱敏后的版本。
"""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from ..models import Dataset, DispatchWorker, ProtocolProfile, Report, Task
from .defaults import (
    LIST_SUMMARY_LIMIT,
    OBSERVATION_JSON_MAX,
    SHORT_TOOLS,
    TOOL_TITLES,
)
from .log import agent_trace
from .long_tasks import assert_short_tool

_SENSITIVE_KEY_RE = re.compile(r"(?i)(api_key|token|password|secret|cookie)")

# 尚未按里程碑交付的短工具：观察记失败，禁止假成功
_UNIMPLEMENTED_TOOLS = frozenset({"kb.list", "testcase.confirm"})


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
        for key in ("task_id", "report_id", "dataset_id", "kb_id", "gold_qa_id", "file_id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                ids.append(value)
    return ids


def summarize_observation(name: str, ok: bool, data: Any, error: str | None, latency_ms: int) -> dict:
    """构造 ReactArtifact.observations 条目。"""
    ids = collect_ids(data) if ok else []
    summary: dict[str, Any] = {"ids": ids[:LIST_SUMMARY_LIMIT]}
    if ok and isinstance(data, dict) and isinstance(data.get("items"), list):
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
            {"id": d.id, "name": d.name, "version": d.version, "row_count": d.row_count}
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


def _report_get(db: Session, arguments: dict) -> dict:
    report_id = str(arguments.get("report_id") or "")
    if not report_id:
        raise AppError(ErrorCode.VALIDATION, "该能力未启用")
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在")
    return {
        "report_id": report.id,
        "summary": (report.metrics or {}).get("summary") if isinstance(report.metrics, dict) else None,
    }


def execute_short_tool(
    db: Session,
    name: str,
    arguments: dict | None,
    *,
    user_id: str,
    allow_create: bool = False,
) -> tuple[bool, Any, str | None, int]:
    """执行一个短工具，返回 (ok, data, error, latency_ms)。

    ``task.create`` 仅当 ``allow_create=True``（ack 后）才执行。
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
            data = _report_get(db, args)
        elif name == "task.cancel":
            raise AppError(ErrorCode.VALIDATION, "请使用会话内取消或 REST /api/tasks/{id}/cancel")
        elif name == "audio.voiceclone":
            from .voiceclone import execute_voiceclone

            data = execute_voiceclone(db, args, user_id=user_id)
        elif name == "image.generate":
            from .imagegen import execute_imagegen

            data = execute_imagegen(db, args, user_id=user_id)
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
