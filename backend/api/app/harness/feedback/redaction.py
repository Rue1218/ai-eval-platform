"""secret / PII / 路径 / 堆栈脱敏。阶段 0 仅最小截断，不改活路径 mcp_tools。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

# 与 app.agent.defaults 对齐；阶段 1 前禁止再导出活路径截断函数，避免双实现。
LIST_SUMMARY_LIMIT = 20
OBSERVATION_JSON_MAX = 4000

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
