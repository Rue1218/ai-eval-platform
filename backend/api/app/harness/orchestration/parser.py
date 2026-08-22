"""严格 JSON 解析与产品裁剪；模型 JSON 不得经 Pydantic 直接写入 trace。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.defaults import SHORT_TOOLS, TOOL_TITLES, WRITE_TOOLS, is_long_tool
from app.agent.log import agent_trace
from app.harness.contracts.tool_call import ToolCall, ToolCallBatch
from app.harness.contracts.trace import TraceContext

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "prompts" / "react-output.schema.json"
_SCHEMA: dict[str, Any] | None = None


@dataclass
class McpStep:
    """模型本轮对短工具的决策（产品适配别名，字段可转到 ToolCall）。"""

    thought: str
    tool: str | None
    arguments: dict[str, Any]
    done: bool
    reply: str
    latency_ms: int = 0
    reasoning_text: str = ""
    missing_tool: bool = False
    model_done: bool | None = None

    def __post_init__(self) -> None:
        """兼容旧测试桩：未显式区分时，``done`` 即视为模型的完成声明。"""
        if self.model_done is None:
            self.model_done = self.done


ReactDecision = McpStep | ToolCallBatch


def _schema() -> dict[str, Any]:
    """读取阶段 0 静态 ReAct JSON Schema。"""
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA


def _type_ok(value: Any, expected: Any) -> bool:
    """JSON Schema type 字段的最小匹配。"""
    names = expected if isinstance(expected, list) else [expected]
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "integer": int,
        "null": type(None),
    }
    return any(value is None if name == "null" else isinstance(value, mapping[name]) for name in names)


def _validate_against(payload: Any, schema: dict[str, Any], *, loc: str) -> None:
    """只覆盖本阶段 Schema 用到的关键字，避免引入 jsonschema 依赖。"""
    variants = schema.get("oneOf")
    if isinstance(variants, list):
        matched = 0
        errors: list[ValueError] = []
        for variant in variants:
            try:
                _validate_against(payload, variant, loc=loc)
            except ValueError as exc:
                errors.append(exc)
                continue
            matched += 1
        if matched == 0 and errors:
            # 保留第一个分支的精确字段诊断，兼容单调用路径既有错误契约。
            raise errors[0]
        if matched != 1:
            raise ValueError(f"ReAct JSON {loc} 未匹配唯一输出分支")
        return
    if not _type_ok(payload, schema.get("type", "object")):
        raise ValueError(f"ReAct JSON {loc} 类型不合法")
    if schema.get("type") == "object" or "properties" in schema:
        if not isinstance(payload, dict):
            raise ValueError(f"ReAct JSON {loc} 必须是 object")
        allowed = set(schema.get("properties") or {})
        if schema.get("additionalProperties") is False:
            extra = set(payload) - allowed
            if extra:
                raise ValueError(f"ReAct JSON {loc} 含禁止字段 {sorted(extra)}")
        for key in schema.get("required") or []:
            if key not in payload:
                raise ValueError(f"ReAct JSON {loc} 缺少字段 {key}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in payload:
                _validate_against(payload[key], sub, loc=f"{loc}.{key}")
        return
    if schema.get("type") == "array":
        if not isinstance(payload, list):
            raise ValueError(f"ReAct JSON {loc} 必须是 array")
        item_schema = schema.get("items") or {}
        for index, item in enumerate(payload):
            _validate_against(item, item_schema, loc=f"{loc}[{index}]")
        return
    if schema.get("type") == "string" and isinstance(payload, str):
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(payload) > max_length:
            raise ValueError(f"ReAct JSON {loc} 超出 maxLength")
    if schema.get("type") == "integer" and isinstance(payload, int) and not isinstance(payload, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and payload < minimum:
            raise ValueError(f"ReAct JSON {loc} 小于 minimum")


def validate_react_output(payload: dict[str, Any]) -> dict[str, Any]:
    """用静态 Schema 校验模型 JSON；拒绝 trace_id 等多余字段。"""
    if not isinstance(payload, dict):
        raise ValueError("ReAct JSON 必须是 object")
    _validate_against(payload, _schema(), loc="$")
    return payload


def parse_mcp_step(raw: dict) -> McpStep:
    """把模型 JSON 收成合法 MCP 步骤。长工具名保留给循环移交，不在此丢弃。"""
    thought = str(raw.get("thought") or "").strip()
    reply = str(raw.get("reply") or "").strip()
    done = bool(raw.get("done"))
    tool_raw = raw.get("tool")
    requested_no_tool = tool_raw in (None, "", "null", "none", "None")
    tool: str | None
    if tool_raw in (None, "", "null", "none", "None"):
        tool = None
    else:
        tool = str(tool_raw).strip()
        if tool in WRITE_TOOLS:
            agent_trace(f"ReAct 丢弃写入工具 name={tool}")
            tool = None
            done = True
        elif is_long_tool(tool):
            done = True
        elif tool not in SHORT_TOOLS:
            agent_trace(f"ReAct 丢弃未知 MCP 工具 name={tool}")
            tool = None
            done = True
    arguments = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
    if not thought:
        if tool:
            thought = f"ToolCall「{TOOL_TITLES.get(tool, tool)}」"
        elif done:
            thought = "本轮观察已足够，停止调用工具"
    return McpStep(
        thought=thought,
        tool=tool,
        arguments=arguments,
        done=done or not tool,
        reply=reply,
        # 仅标记模型明确要求继续却未给动作；未知/写/长工具沿用既有静默停止语义。
        missing_tool=not done and requested_no_tool,
        model_done=done,
    )


def tool_call_from_step(step: McpStep) -> ToolCall:
    """产品步骤转为 ToolCall；不拷贝模型可能伪造的 trace。"""
    return ToolCall(
        thought=step.thought,
        tool=step.tool,
        arguments=dict(step.arguments or {}),
        done=step.done,
        reply=step.reply,
    )


def parse_model_payload(raw: dict[str, Any], *, trace: TraceContext) -> ReactDecision:
    """解析模型结构化输出并绑定 Turn；批次 span 仅由编排执行阶段创建。"""
    validated = validate_react_output(raw)
    if "tool_calls" not in validated:
        return parse_mcp_step(validated)

    calls: list[ToolCall] = []
    for item in validated.get("tool_calls") or []:
        # 复用产品工具裁剪：未知工具/长任务保持既有不执行语义。
        step = parse_mcp_step(
            {
                "thought": validated.get("thought") or "",
                "tool": item.get("tool"),
                "arguments": item.get("arguments"),
                "done": False,
                "reply": "",
            }
        )
        if not step.tool or step.done:
            continue
        call_payload: dict[str, Any] = {
            "tool": step.tool,
            "arguments": step.arguments,
            "thought": str(validated.get("thought") or ""),
            "done": False,
            "reply": "",
            "trace_id": trace.trace_id,
        }
        if str(item.get("call_id") or "").strip():
            call_payload["call_id"] = str(item["call_id"])
        calls.append(ToolCall(**call_payload))

    return ToolCallBatch(
        turn_id=trace.turn_id,
        thought=str(validated.get("thought") or ""),
        done=bool(validated.get("done")),
        reply=str(validated.get("reply") or ""),
        tool_calls=calls,
    )
