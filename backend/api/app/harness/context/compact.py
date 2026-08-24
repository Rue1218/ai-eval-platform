"""Harness 上下文工程层：/compact 可控摘要 + CompactProtocol（M2 阶段 3，CX-6）。

可控摘要：保留最近 ``keep_recent`` 条原始消息、摘要 ≤2000 字符、**不删除
原始记录**（原始与摘要冲突时原始优先，MEM-3）。CompactProtocol 为压缩阶段
严格 JSON 输出协议（M1-Q5 移归本层），版本严格不兼容（拒绝旧版）。
本层只产出摘要文本，写入 ``sessions.compact_summary`` 由 M3 承担。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Literal, TypedDict

from app.errors import AppError, ErrorCode

ProtocolVersion = str  # 如 "compact.v1"

COMPACT_VERSION: ProtocolVersion = "compact.v1"

# 默认保留最近原始消息条数与摘要上限（CX-6）
DEFAULT_KEEP_RECENT = 6
DEFAULT_MAX_SUMMARY_CHARS = 2000

# 压缩阶段严格 JSON schema（summary/kept_ids/token_count）
COMPACT_SCHEMA: dict = {
    "properties": {
        "summary": {"type": "string"},
        "kept_ids": {"type": "array", "items": {"type": "string"}},
        "token_count": {"type": "integer"},
        "protocol": {"type": "string"},
        "version": {"type": "string"},
    },
    "required": ["summary", "kept_ids", "token_count", "protocol", "version"],
}

# 代码块包裹提取（模型可能以 ```json 包裹输出）
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class CompactProtocolResult(TypedDict, total=False):
    """压缩协议统一解析结果。"""

    protocol: Literal["compact"]
    version: ProtocolVersion
    fields: Mapping[str, object]  # summary/kept_ids/token_count


def parse_compact(raw: str) -> CompactProtocolResult:
    """压缩协议严格 JSON 解析 + schema 校验；失败抛 AppError(VALIDATION)。

    summary ≤2000 字符（CX-6）；版本严格不兼容（拒绝旧版）。
    """
    text = raw.strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.VALIDATION, "压缩输出不是有效 JSON") from exc
    if not isinstance(data, dict):
        raise AppError(ErrorCode.VALIDATION, "压缩输出必须是 JSON 对象")
    if data.get("protocol") != "compact":
        raise AppError(ErrorCode.VALIDATION, "协议声明不匹配，期望 compact")
    properties = COMPACT_SCHEMA["properties"]
    extra = set(data.keys()) - set(properties.keys())
    if extra:
        raise AppError(ErrorCode.VALIDATION, f"压缩协议包含多余字段：{sorted(extra)}")
    for name in COMPACT_SCHEMA["required"]:
        if name not in data:
            raise AppError(ErrorCode.VALIDATION, f"压缩协议缺少必填字段：{name}")
    if not isinstance(data["summary"], str) or len(data["summary"]) > DEFAULT_MAX_SUMMARY_CHARS:
        raise AppError(ErrorCode.VALIDATION, "压缩摘要超长或类型非法")
    if not isinstance(data["kept_ids"], list) or not all(
        isinstance(item, str) for item in data["kept_ids"]
    ):
        raise AppError(ErrorCode.VALIDATION, "kept_ids 必须为字符串数组")
    if not isinstance(data["token_count"], int) or isinstance(data["token_count"], bool):
        raise AppError(ErrorCode.VALIDATION, "token_count 必须为整数")
    version = str(data.get("version", ""))
    if version != COMPACT_VERSION:
        raise AppError(
            ErrorCode.VALIDATION,
            f"压缩协议版本不匹配：期望 {COMPACT_VERSION}，收到 {version or '（缺失）'}",
        )
    fields = {name: value for name, value in data.items() if name not in ("protocol", "version")}
    return CompactProtocolResult(protocol="compact", version=version, fields=fields)


def summarize(
    messages: list[Mapping[str, object]],
    *,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    max_summary_chars: int = DEFAULT_MAX_SUMMARY_CHARS,
) -> tuple[str, list[str]]:
    """可控摘要：保留最近 keep_recent 条原始消息，产出摘要文本 ≤max_summary_chars。

    返回 ``(summary, kept_ids)``；**不删除原始记录**（CX-6/MEM-3）。
    摘要文本交 M3 写入 ``sessions.compact_summary``。
    当前为确定性截断摘要（不调模型，保证可离线测试）；LLM 压缩接入后
    经 ``parse_compact`` 严格校验后写库。
    """
    kept = messages[-keep_recent:] if keep_recent > 0 else []
    kept_ids = [
        str(message.get("source_id") or f"idx:{index}")
        for index, message in enumerate(kept)
    ]
    if not messages:
        return "", kept_ids
    # 确定性摘要：合并历史消息正文，超长截断带标记
    body = "\n".join(
        f"{message.get('role', 'user')}: {message.get('content', '')}"
        for message in messages[: -keep_recent or None]
    ) or "（无历史消息可压缩）"
    if len(body) > max_summary_chars:
        body = body[:max_summary_chars] + "…[截断]"
    return body, kept_ids
