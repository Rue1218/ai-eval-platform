"""从模型输出中容错提取 JSON 候选数组。"""

from __future__ import annotations

import json

from app.errors import AppError, ErrorCode


def parse_json_candidates(text: str) -> list[dict]:
    """从模型输出中容错提取 JSON 数组（允许 ```json 代码块或首尾解释文字）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型未返回可解析的候选 JSON 数组")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型候选 JSON 解析失败") from exc
    if not isinstance(data, list):
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型候选格式不是数组")
    return [item for item in data if isinstance(item, dict)]
