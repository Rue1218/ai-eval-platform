"""最小 MCP 工具内核：仅保留图像生成与音色克隆。"""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from .defaults import (
    LIST_SUMMARY_LIMIT,
    OBSERVATION_JSON_MAX,
    SHORT_TOOLS,
    TOOL_TITLES,
)
from .log import agent_exception, agent_trace
from .long_tasks import assert_short_tool
from .mcp_registry import execute_registered_tool, get_tool_definition

_SENSITIVE_KEY_RE = re.compile(r"(?i)(api_key|token|password|secret|cookie)")


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


def execute_short_tool(
    db: Session,
    name: str,
    arguments: dict | None,
    *,
    user_id: str,
    allow_create: bool = False,
) -> tuple[bool, Any, str | None, int]:
    """执行一个短工具，返回 (ok, data, error, latency_ms)。

    ``allow_create`` 仅为兼容旧调用点保留，当前没有 MCP 任务写入能力。
    """
    started = time.perf_counter()
    args = arguments if isinstance(arguments, dict) else {}
    try:
        assert_short_tool(name)
        tool = get_tool_definition(name)
        if tool is None or name not in SHORT_TOOLS:
            raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")
        data = execute_registered_tool(db, tool.name, args, user_id=user_id)

        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_trace(f"ToolCall 完成 name={name} ok=true latency={latency_ms}ms")
        return True, truncate_tool_data(data), None, latency_ms
    except AppError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_trace(f"ToolCall 失败 name={name} code={exc.code.value} latency={latency_ms}ms error={exc.message}")
        return False, None, exc.message, latency_ms
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_exception(f"ToolCall 内部异常 name={name}", exc)
        raise AppError(ErrorCode.INTERNAL, f"ToolCall「{name}」执行失败") from exc


def tool_title(name: str) -> str:
    """工具卡中文名。"""
    tool = get_tool_definition(name)
    return tool.title if tool else TOOL_TITLES.get(name, name)
