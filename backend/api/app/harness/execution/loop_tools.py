"""新循环的工具契约；仅依赖鸭子类型，不引入第二套工具注册生态。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from app.harness.contracts import ToolResult
from app.llm.loop_contracts import ToolSpec

from .native_results import clip_for_store
from .registry import validate_tool_arguments

ToolResultStatus = Literal[
    "succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown"
]
ToolExecutionMode = Literal["parallel", "exclusive"]


@dataclass(frozen=True)
class ToolExecutionResult:
    """工具六态事实；正文用于模型回填，展示投影不参与成功判断。"""

    content: str
    status: ToolResultStatus
    error_code: str | None = None
    exit_code: int | None = None
    synthetic: bool = False
    display: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """拒绝把未知终态默认为成功。"""
        if self.status not in {
            "succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown"
        }:
            raise ValueError("非法工具终态")

    @property
    def is_error(self) -> bool:
        """兼容字段只由六态派生。"""
        return self.status != "succeeded"

    @property
    def ok(self) -> bool:
        """兼容平台旧结果字段。"""
        return not self.is_error


def execution_mode(tool: object | None) -> ToolExecutionMode:
    """未知工具、写操作和交互都以独占屏障处理。"""
    metadata = getattr(tool, "metadata", None) or {}
    return "parallel" if isinstance(metadata, Mapping) and metadata.get("dsh_execution_mode") == "parallel" else "exclusive"


def requires_approval(tool: object) -> bool:
    """只读观察免审批，其余按声明裁决；平台权限仍逐次独立检查。"""
    metadata = getattr(tool, "metadata", None) or {}
    if not isinstance(metadata, Mapping):
        return True
    return bool(metadata.get("dsh_requires_approval", metadata.get("dsh_access") != "read"))


def tool_schema(tool: object) -> dict[str, Any]:
    """接受普通 schema 字典/方法，兼容具备模型校验器的鸭子类型。"""
    schema = getattr(tool, "schema", None)
    if callable(schema):
        schema = schema()
    if isinstance(schema, Mapping):
        return deepcopy(dict(schema))
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        return deepcopy(args_schema.model_json_schema())
    return {"type": "object", "properties": {}, "additionalProperties": False}


def tool_argument_error(tool: object, args: dict[str, Any]) -> str | None:
    """派发前校验；平台桥可先完成显式版本化别名归一。"""
    validator = getattr(tool, "argument_error", None)
    if validator is not None:
        return validator(args)
    schema = tool_schema(tool)
    unknown = set(args) - set(schema.get("properties", {}))
    if unknown:
        return "不支持的工具字段：" + ", ".join(sorted(unknown))
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        try:
            args_schema.model_validate(args)
        except (TypeError, ValueError):
            return "工具参数不符合 Schema"
        return None
    return validate_tool_arguments(schema, args)


def tool_spec(tool: object) -> ToolSpec:
    """由注册表投影保留完整嵌套 Schema，不另写工具定义。"""
    parameters = tool_schema(tool)
    parameters.pop("title", None)
    parameters.pop("description", None)
    parameters["additionalProperties"] = False
    return ToolSpec(
        name=tool.name, description=getattr(tool, "description", ""), parameters=parameters
    )


def normalize_tool_output(output: object) -> ToolExecutionResult:
    """结构化平台结果优先，文本兼容仅用于明确采用源文本契约的工具。"""
    if isinstance(output, ToolExecutionResult):
        content, truncated = clip_for_store(output.content)
        return replace(output, content=content, metadata={**output.metadata, "truncated": True}) if truncated else output
    if isinstance(output, ToolResult):
        data, error = dict(output.data), dict(output.error)
        code = str(error.get("code") or "tool_error") if not output.ok else None
        # 业务 data.status=queued 不等于工具失败，且正文不能用 display 摘要替代。
        content = data.get("model_text", data.get("content", data.get("summary"))) if output.ok else None
        if content is None:
            content = json.dumps(data if output.ok else error, ensure_ascii=False)
        content, truncated = clip_for_store(str(content))
        status: ToolResultStatus = "succeeded" if output.ok else "failed"
        if code in {"UNAUTHORIZED", "WHITELIST", "NEED_APPROVAL"}:
            status = "denied"
        return ToolExecutionResult(
            content=content, status=status, error_code=code,
            exit_code=data.get("exit_code"), display=deepcopy(data.get("display") or {}),
            metadata={**deepcopy(data.get("metadata") or {}), "truncated": truncated or bool(data.get("truncated"))},
        )
    if not isinstance(output, str):
        return ToolExecutionResult("工具返回值缺少明确结果契约", "failed", "invalid_tool_result")
    if output.lower().startswith("error:"):
        return ToolExecutionResult(output, "failed", "tool_error")
    if output.startswith("exit code: "):
        try:
            code = int(output.partition("\n")[0].removeprefix("exit code: ").strip())
        except ValueError:
            code = None
        if code not in (None, 0):
            return ToolExecutionResult(output, "failed", "nonzero_exit", code)
        return ToolExecutionResult(output, "succeeded", exit_code=code)
    return ToolExecutionResult(output, "succeeded")
