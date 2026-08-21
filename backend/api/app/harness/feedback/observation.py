"""工具观察摘要：供 ReactArtifact 与复核 G3 溯源。"""

from __future__ import annotations

from typing import Any

from app.harness.feedback.redaction import LIST_SUMMARY_LIMIT


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
