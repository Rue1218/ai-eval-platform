"""Harness 提示词工程层：各阶段严格 JSON 输出协议（M1 阶段 1/4，PR-2/PR-3）。

定义规划/ReAct/复核三阶段 JSON schema 与解析校验（压缩协议 CompactProtocol
归 M2 上下文层）。协议版本演进为**严格不兼容**（旧版直接拒绝，无兼容窗口）。
解析链路只消费授权字段（PR-3：ReAct 协议忽略 thought，thought 只回显不触发动作）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Literal, TypedDict

from app.errors import AppError, ErrorCode

ProtocolName = Literal["plan", "react", "reflect", "router"]  # compact 归 M2，不在本层
ProtocolVersion = str  # 如 "plan.v1"、"react.v1"

# 各协议当前版本（严格不兼容：旧版直接拒绝）
PLAN_VERSION: ProtocolVersion = "plan.v1"
REACT_VERSION: ProtocolVersion = "react.v1"
REFLECT_VERSION: ProtocolVersion = "reflect.v1"
ROUTER_VERSION: ProtocolVersion = "router.v1"

# 期望协议名（模型输出须声明，防止跨协议误用）
_EXPECTED_PROTOCOL = {"plan": "plan", "react": "react", "reflect": "reflect", "router": "router"}


class ProtocolResult(TypedDict, total=False):
    """统一解析结果；授权字段随协议不同。"""

    protocol: ProtocolName
    version: ProtocolVersion
    fields: Mapping[str, object]  # 仅授权字段（PR-3 过滤 thought 等）


# 各协议 schema（声明式；properties 即白名单，多余字段拒绝）
PLAN_SCHEMA: dict = {
    "properties": {
        "intent": {"type": "string"},
        "skill_id": {"type": ["string", "null"]},
        "slots": {"type": "object"},
        "tools_needed": {"type": "array", "items": {"type": "string"}},
        "delivery": {"enum": ["chat", "confirm"]},
        "budget": {"type": "object"},
        "allows_replan": {"type": "boolean"},
        "notes": {"type": "string"},
        "protocol": {"type": "string"},
        "version": {"type": "string"},
    },
    "required": [
        "intent",
        "skill_id",
        "slots",
        "tools_needed",
        "delivery",
        "budget",
        "allows_replan",
        "notes",
        "protocol",
        "version",
    ],
}

REACT_SCHEMA: dict = {
    "properties": {
        "thought": {"type": "string"},  # 动作摘要，解析后丢弃（PR-3）
        "tool": {"type": ["string", "null"]},
        "arguments": {"type": "object"},
        "done": {"type": "boolean"},
        "protocol": {"type": "string"},
        "version": {"type": "string"},
    },
    "required": ["thought", "tool", "arguments", "done", "protocol", "version"],
}

REFLECT_SCHEMA: dict = {
    "properties": {
        "verdict": {"enum": ["pass", "clarify", "reject"]},
        "reason": {"type": "string"},
        "clarify_question": {"type": ["string", "null"]},
        "protocol": {"type": "string"},
        "version": {"type": "string"},
    },
    "required": ["verdict", "reason", "protocol", "version"],
}

# Router 分流协议（H1，ADR-1 裁决：JSON，不接受 <Intent>/<Reasoning> XML 标签）。
# skill_id / slots 为可选：仅 engine=workflow 且 L1 能识别具体技能时携带，
# H1 阶段只作审计痕迹（并入 router_reason），H2 select_skill 节点才消费。
ROUTER_SCHEMA: dict = {
    "properties": {
        "engine": {"enum": ["direct", "chat", "workflow", "agent"]},
        "skill_id": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "slots": {"type": "object"},
        "protocol": {"type": "string"},
        "version": {"type": "string"},
    },
    "required": ["engine", "confidence", "reason", "protocol", "version"],
}

# 代码块包裹提取（模型可能以 ```json 包裹输出）
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _extract_json_object(text: str) -> str | None:
    """从含前后自然语言的文本中提取第一个平衡的 ``{...}`` 对象。

    模型常在协议 JSON 前后附加说明文字（如"好的，我先读取文件。{...} 然后继续"）。
    逐字符扫描保持字符串内 ``{}`` 与转义正确，避免 ``re`` 的贪婪/非贪婪误截。
    提取不到返回 None，由调用方回退为原错误路径。
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _loads_strict(raw: str) -> dict:
    """严格 JSON 解析；容忍首尾空白、```json 代码块包裹与前后说明文字。"""
    text = raw.strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        candidate = _extract_json_object(text)
        if candidate is None:
            raise AppError(ErrorCode.VALIDATION, "模型输出不是有效 JSON")
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.VALIDATION, "模型输出不是有效 JSON") from exc
    if not isinstance(data, dict):
        raise AppError(ErrorCode.VALIDATION, "模型输出必须是 JSON 对象")
    return data


def _check_type(value: object, spec: dict, path: str) -> None:
    """按 schema 的 type/enum/items 检查单个字段。"""
    if "enum" in spec:
        if value not in spec["enum"]:
            raise AppError(ErrorCode.VALIDATION, f"字段 {path} 取值非法")
        if "type" not in spec:
            return  # 纯 enum 约束（如 reflect.verdict），enum 通过即可
    allowed = spec.get("type", [])
    type_list = allowed if isinstance(allowed, list) else [allowed]
    for kind in type_list:
        if kind == "string" and isinstance(value, str):
            return
        if kind == "object" and isinstance(value, dict):
            return
        if kind == "boolean" and isinstance(value, bool):
            return
        if kind == "array" and isinstance(value, list):
            return
        if kind == "null" and value is None:
            return
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return
        if kind == "number" and isinstance(value, int | float) and not isinstance(value, bool):
            return
    raise AppError(ErrorCode.VALIDATION, f"字段 {path} 类型非法")


def _validate_schema(data: dict, schema: dict, protocol: str) -> None:
    """schema 校验：拒绝缺字段/多字段/类型非法（P-A2）。"""
    properties = schema["properties"]
    extra = set(data.keys()) - set(properties.keys())
    if extra:
        raise AppError(ErrorCode.VALIDATION, f"协议 {protocol} 包含多余字段：{sorted(extra)}")
    for name in schema["required"]:
        if name not in data:
            raise AppError(ErrorCode.VALIDATION, f"协议 {protocol} 缺少必填字段：{name}")
    for name, value in data.items():
        _check_type(value, properties[name], name)


def _parse(raw: str, protocol: str, schema: dict, expected_version: str) -> ProtocolResult:
    """通用解析：严格 JSON → schema 校验 → 协议名/版本校验。"""
    data = _loads_strict(raw)
    declared_protocol = data.get("protocol")
    if declared_protocol != _EXPECTED_PROTOCOL[protocol]:
        raise AppError(ErrorCode.VALIDATION, f"协议声明不匹配，期望 {protocol}")
    _validate_schema(data, schema, protocol)
    check_version(str(data.get("version", "")), expected_version)
    fields = {name: value for name, value in data.items() if name not in ("protocol", "version")}
    return ProtocolResult(protocol=protocol, version=data["version"], fields=fields)


def check_version(declared: str, expected: ProtocolVersion) -> None:
    """协议版本匹配校验；不匹配抛 AppError(VALIDATION)（P-A5）。

    严格不兼容策略：旧版直接拒绝，无兼容窗口。
    """
    if declared != expected:
        raise AppError(
            ErrorCode.VALIDATION,
            f"协议版本不匹配：期望 {expected}，收到 {declared or '（缺失）'}",
        )


def parse_plan_protocol(raw: str) -> ProtocolResult:
    """规划协议严格 JSON + PLAN_SCHEMA 校验；失败抛 AppError(VALIDATION)。

    返回 fields 仅含授权字段。供 M4 ``build_plan`` 内部调用（协议解析层，
    不负责重试/降级）。
    """
    return _parse(raw, "plan", PLAN_SCHEMA, PLAN_VERSION)


def parse_react(raw: str) -> ProtocolResult:
    """ReAct 协议解析；**忽略 thought**（PR-3），只返回 tool/arguments/done。"""
    result = _parse(raw, "react", REACT_SCHEMA, REACT_VERSION)
    fields = dict(result["fields"])
    fields.pop("thought", None)  # thought 是动作摘要，不是授权依据
    return ProtocolResult(protocol="react", version=result["version"], fields=fields)


def parse_reflect(raw: str) -> ProtocolResult:
    """复核协议解析；verdict ∈ {pass, clarify, reject}。"""
    return _parse(raw, "reflect", REFLECT_SCHEMA, REFLECT_VERSION)


def parse_router(raw: str) -> ProtocolResult:
    """Router 分流协议解析；engine ∈ {direct, chat, workflow, agent}。

    仅消费授权字段（engine / skill_id / confidence / reason / slots）；
    解析失败抛 AppError(VALIDATION)，由 router 节点回落 L0，不重试。
    """
    return _parse(raw, "router", ROUTER_SCHEMA, ROUTER_VERSION)
