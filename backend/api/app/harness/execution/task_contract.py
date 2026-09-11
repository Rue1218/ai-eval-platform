"""评测任务工具的稳定命名契约。

``task.create``、``task.status``、``task.cancel`` 同时存在三种受控名称：
注册表短名、模型 Function Calling 的安全 wire 名，以及内部 MCP 目录全名。
本模块只负责名称归一，不复制参数 Schema 或 handler，二者仍以
``ToolRegistry`` 的 ``ToolDef.parameters_schema`` 为唯一事实源。
"""

# 三项长任务桥的注册名顺序同时用于工具快照和回归用例，禁止从前端反推。
TASK_TOOL_NAMES = ("task.create", "task.status", "task.cancel")

# 部分 Function Calling 提供方只接受字母、数字和下划线；Agent 对模型稳定暴露此名。
TASK_TOOL_WIRE_NAMES = {
    "task.create": "platform_task_create",
    "task.status": "platform_task_status",
    "task.cancel": "platform_task_cancel",
}

# MCP Host 目录与服务端调用统一使用完整 tool_id，模型参数中不得传 server_id。
TASK_TOOL_MCP_NAMES = {
    "task.create": "platform.tasks.task.create",
    "task.status": "platform.tasks.task.status",
    "task.cancel": "platform.tasks.task.cancel",
}

_TASK_TOOL_CANONICAL_NAMES = {
    **{name: name for name in TASK_TOOL_NAMES},
    **{wire: name for name, wire in TASK_TOOL_WIRE_NAMES.items()},
    **{tool_id: name for name, tool_id in TASK_TOOL_MCP_NAMES.items()},
}


def canonical_task_tool_name(name: str) -> str:
    """把已登记任务别名归一为注册表短名；未知名称保持原样。"""
    return _TASK_TOOL_CANONICAL_NAMES.get(name, name)


def task_tool_wire_name(registry_name: str) -> str | None:
    """返回模型侧安全名称；非任务工具由调用方沿用通用转换规则。"""
    return TASK_TOOL_WIRE_NAMES.get(registry_name)


def task_tool_aliases(registry_name: str) -> tuple[str, ...]:
    """返回同一任务工具允许回传的三种既有名称，顺序以安全 wire 名优先。"""
    wire_name = TASK_TOOL_WIRE_NAMES.get(registry_name)
    mcp_name = TASK_TOOL_MCP_NAMES.get(registry_name)
    if wire_name is None or mcp_name is None:
        return ()
    return wire_name, registry_name, mcp_name
