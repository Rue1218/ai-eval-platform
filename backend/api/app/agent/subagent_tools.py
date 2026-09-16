"""专家协作模型工具契约；执行由当前主回合的协调器回调完成。"""

from __future__ import annotations

from app.harness.execution.policy import ToolPermissionPolicy
from app.harness.execution.registry import ToolDef, ToolRegistry


def _unwired(*_args, **_kwargs):
    """防御性占位；agent.* 必须经 PlatformToolBridge 的协作回调。"""
    raise RuntimeError("agent tool is not wired")


def _tool(name: str, description: str, schema: dict, *, risk: str = "read") -> ToolDef:
    """构造不触碰工作区、只访问受控协作状态的短工具。"""
    return ToolDef(
        name=name,
        description=description,
        parameters_schema=schema,
        permission="agent.collaboration",
        timeout_s=35.0,
        handler=_unwired,
        output_schema={"type": "object"},
        permission_policy=ToolPermissionPolicy(workspace="none"),
        transport="native",
        display_name=name,
        risk_level=risk,
        execution_mode="short",
        concurrency_class="exclusive",
    )


def register_subagent_tools(registry: ToolRegistry) -> None:
    """登记 P1 六个调度工具；身份、run_id 与幂等键均由平台补齐。"""
    registry.register(_tool("agent.list", "列出本回合可以调度的专家及能力摘要。", {
        "type": "object", "additionalProperties": False,
        "properties": {"capability": {"type": "string", "maxLength": 200}},
    }))
    registry.register(_tool("agent.spawn", "创建一个独立专家运行并立即开始执行，目标和交付格式必须明确。", {
        "type": "object", "additionalProperties": False,
        "properties": {
            "expert_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "goal": {"type": "string", "minLength": 1, "maxLength": 12000},
            "output_contract": {"type": "string", "minLength": 1, "maxLength": 4000},
            "profile_id": {"type": "string", "minLength": 1, "maxLength": 128},
        },
        "required": ["expert_id", "goal", "output_contract"],
    }, risk="modify"))
    ids = {
        "type": "array", "minItems": 1, "maxItems": 8,
        "items": {"type": "string", "minLength": 1, "maxLength": 128},
    }
    registry.register(_tool("agent.status", "查询一个或多个专家运行的状态和结果可用性。", {
        "type": "object", "additionalProperties": False,
        "properties": {"run_ids": ids}, "required": ["run_ids"],
    }))
    registry.register(_tool("agent.wait", "有界等待专家运行出现新状态；等待期间不占模型调用槽位。", {
        "type": "object", "additionalProperties": False,
        "properties": {
            "run_ids": ids,
            "mode": {"type": "string", "enum": ["any", "all"]},
            "timeout_seconds": {"type": "integer", "minimum": 0, "maximum": 30},
        },
        "required": ["run_ids"],
    }))
    registry.register(_tool("agent.result", "读取专家已提交的最终结果和覆盖范围。", {
        "type": "object", "additionalProperties": False,
        "properties": {"run_id": {"type": "string", "minLength": 1, "maxLength": 128}},
        "required": ["run_id"],
    }))
    registry.register(_tool("agent.cancel", "请求停止指定专家运行；返回请求是否已持久化。", {
        "type": "object", "additionalProperties": False,
        "properties": {
            "run_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "reason": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["run_id", "reason"],
    }, risk="modify"))
