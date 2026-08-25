"""内部 MCP provider（阶段 D，P3）：in-process 包装注册表 handler。

迁移初期用 in-process provider 包装当前 handler（§9 阶段 D.3），保持既有
路径/SSRF/bwrap 沙箱与脱敏边界不变；不引入 stdio transport，浏览器不可连接。
Agent 图只能依赖 ``MCPClientManager``，不得直接导入 dispatch handler。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.harness.contracts import ToolCall, ToolResult

from ..dispatch import execute_raw
from ..registry import ToolDef


@dataclass(frozen=True, slots=True)
class InProcessProvider:
    """平台内置 provider：同一 server 内以 tool_id 分派到注册表 handler。"""

    server_id: str
    _defs: dict[str, ToolDef]  # tool_id -> ToolDef（含 handler）

    def invoke(
        self,
        tool_id: str,
        arguments: dict,
        sandbox_dir: str | None = None,
        call_id: str = "",
    ) -> ToolResult:
        """执行短工具，返回 ToolResult（不抛，错误归一）。

        未登记 tool_id 属防御路径（正常由 catalog 先行解析）；其余委托
        ``execute_raw`` 保持既有超时/脱敏/错误归一语义。
        """
        definition = self._defs.get(tool_id)
        if definition is None:
            return ToolResult(
                name=tool_id,
                ok=False,
                error={"code": "VALIDATION", "message": f"工具未注册：{tool_id}"},
                call_id=call_id,
            )
        return execute_raw(
            ToolCall(name=definition.name, arguments=arguments, call_id=call_id),
            timeout_s=definition.timeout_s,
            permission=definition.permission,
            sandbox_dir=sandbox_dir,
            handler=definition.handler,
        )
