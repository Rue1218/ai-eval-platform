"""同轮原生 ToolCall 的显式批次与受控并行调度（P2/P3）。

批次只描述「这一次上游响应里按原始顺序待执行的调用」。GraphState 只保存
可序列化元数据，不含 Observation 原文。并行资格由注册表并发类决定，不由
模型声明依赖。
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import uuid4

BatchItemStatus = Literal["pending", "succeeded", "failed"]
_TERMINAL: frozenset[str] = frozenset({"succeeded", "failed"})
# P3 首批可并行工具；task.status / task 虽为 read_only，仍保持串行直至评审扩大。
PARALLEL_ELIGIBLE_NAMES: frozenset[str] = frozenset({"read", "web_search", "web_fetch"})


def build_tool_batch(
    calls: Sequence[Mapping[str, object]],
    *,
    batch_id: str | None = None,
) -> dict[str, object]:
    """按模型给出的原始顺序构造 ToolBatch。"""
    items: list[dict[str, object]] = []
    for index, call in enumerate(calls):
        items.append(
            {
                "call_id": str(call.get("call_id") or ""),
                "name": str(call.get("name") or ""),
                "arguments": dict(call.get("arguments") or {}),
                "native": bool(call.get("native", True)),
                "block_index": index,
                "status": "pending",
            }
        )
    return {
        "batch_id": batch_id or f"batch_{uuid4().hex}",
        "items": items,
    }


def batch_item_to_pending(item: Mapping[str, object]) -> dict[str, object]:
    """把批次项投影回 ToolNode 消费的 pending_tool 形状。"""
    return {
        "call_id": str(item.get("call_id") or ""),
        "name": str(item.get("name") or ""),
        "arguments": dict(item.get("arguments") or {}),
        "native": bool(item.get("native", True)),
    }


def mark_batch_item(
    batch: Mapping[str, object],
    call_id: str,
    status: BatchItemStatus,
) -> dict[str, object]:
    """返回更新指定 call_id 终态后的批次副本，不修改入参。"""
    items: list[dict[str, object]] = []
    for raw in batch.get("items") or ():
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        if str(item.get("call_id") or "") == call_id:
            item["status"] = status
        items.append(item)
    return {"batch_id": str(batch.get("batch_id") or ""), "items": items}


def mark_batch_items(
    batch: Mapping[str, object],
    updates: Sequence[tuple[str, BatchItemStatus]],
) -> dict[str, object]:
    """按顺序应用多项终态，供并行波次一次性回写。"""
    updated = dict(batch)
    for call_id, status in updates:
        updated = mark_batch_item(updated, call_id, status)
    return updated


def pending_batch_items(batch: Mapping[str, object] | None) -> list[dict[str, object]]:
    """按 block_index 返回尚未终态的项。"""
    if not batch:
        return []
    items = [
        dict(raw)
        for raw in (batch.get("items") or ())
        if isinstance(raw, Mapping) and str(raw.get("status") or "pending") not in _TERMINAL
    ]
    items.sort(key=lambda item: int(item.get("block_index") or 0))
    return items


def batch_is_complete(batch: Mapping[str, object] | None) -> bool:
    """批次存在且全部项已终态。"""
    if not batch:
        return False
    items = [raw for raw in (batch.get("items") or ()) if isinstance(raw, Mapping)]
    return bool(items) and all(str(item.get("status") or "") in _TERMINAL for item in items)


def native_result_messages(batch: Mapping[str, object]) -> list[dict[str, object]]:
    """按原始 block_index 组装 role=tool 回填消息；正文仍只存在临时存储。"""
    items = [dict(raw) for raw in (batch.get("items") or ()) if isinstance(raw, Mapping)]
    items.sort(key=lambda item: int(item.get("block_index") or 0))
    return [
        {
            "role": "tool",
            "tool_call_id": str(item.get("call_id") or ""),
            "name": str(item.get("name") or ""),
            "content": "",
        }
        for item in items
    ]


def normalize_workspace_path(path: object, sandbox_dir: str = "") -> str:
    """规范化工作区相对路径，禁止用原始字符串比较资源键。"""
    raw = str(path or "").replace("\\", "/").strip()
    if not raw:
        return ""
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    logical = "/".join(parts)
    if not sandbox_dir:
        return os.path.normcase(logical)
    try:
        root_real = os.path.realpath(sandbox_dir)
        target = os.path.realpath(os.path.join(root_real, *parts) if parts else root_real)
        if not (target.startswith(root_real + os.sep) or target == root_real):
            return f"invalid:{os.path.normcase(logical)}"
        return os.path.normcase(target)
    except OSError:
        return os.path.normcase(logical)


def is_parallel_eligible(
    name: str,
    concurrency_class: str,
    *,
    requires_prior_result: bool = False,
) -> bool:
    """P3 首批：仅 read / web_search / web_fetch 且无副作用屏障。"""
    if requires_prior_result or name not in PARALLEL_ELIGIBLE_NAMES:
        return False
    if concurrency_class == "read_only":
        return True
    return concurrency_class == "path_scoped" and name == "read"


def tool_resource_key(
    name: str,
    concurrency_class: str,
    arguments: Mapping[str, object] | None,
    sandbox_dir: str = "",
) -> str:
    """返回冲突检测键：空字符串表示无本地资源。"""
    if concurrency_class == "exclusive":
        return "workspace"
    if concurrency_class == "session_exclusive":
        return "session"
    if concurrency_class == "path_scoped":
        return normalize_workspace_path((arguments or {}).get("path"), sandbox_dir)
    return ""


def _resource_mode(name: str, concurrency_class: str) -> str:
    """read/write/none，供同路径读写冲突判断。"""
    if concurrency_class != "path_scoped":
        return "none"
    if name in {"write", "edit"}:
        return "write"
    return "read"


def _conflicts(
    occupied: Sequence[tuple[str, str]],
    key: str,
    mode: str,
) -> bool:
    """同资源写冲突或独占键冲突。只读同路径不冲突。"""
    if not key:
        return False
    for existing_key, existing_mode in occupied:
        if existing_key != key:
            continue
        if existing_mode == "read" and mode == "read":
            return False
        return True
    return False


def select_execution_wave(
    items: Sequence[Mapping[str, object]],
    *,
    class_of: Mapping[str, str],
    enabled: bool,
    max_parallel: int,
    sandbox_dir: str = "",
    prior_of: Mapping[str, bool] | None = None,
) -> list[dict[str, object]]:
    """从待执行队列头部切出本波次。开关关闭或上限≤1 时恒为单项。"""
    pending = [dict(item) for item in items if isinstance(item, Mapping)]
    if not pending:
        return []
    limit = max(1, int(max_parallel or 1))
    if not enabled or limit <= 1:
        return [pending[0]]

    wave: list[dict[str, object]] = []
    occupied: list[tuple[str, str]] = []
    requires_prior = prior_of or {}
    for item in pending:
        name = str(item.get("name") or "")
        concurrency = str(class_of.get(name) or "exclusive")
        eligible = is_parallel_eligible(
            name,
            concurrency,
            requires_prior_result=bool(requires_prior.get(name)),
        )
        key = tool_resource_key(name, concurrency, item.get("arguments") or {}, sandbox_dir)
        mode = _resource_mode(name, concurrency)
        if not wave:
            wave.append(item)
            if not eligible:
                break
            if key:
                occupied.append((key, mode if mode != "none" else "write"))
            continue
        if not eligible or _conflicts(occupied, key, mode) or len(wave) >= limit:
            break
        wave.append(item)
        if key:
            occupied.append((key, mode if mode != "none" else "write"))
    return wave
