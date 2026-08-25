"""内部 MCP Host（阶段 D，P3）。

``catalog``（平台 allowlist 工具目录：目录/风险/策略唯一源）→ ``provider``
（in-process 包装注册表 handler）→ ``manager``（``MCPClientManager``：
tools/list + tools/call + 超时/取消/错误归一）。

仅连接平台部署、审计、允许列表内的**内部**工具；不接外部 MCP Server，
浏览器不可直接调用 ``tools/call``（MCP 传输不暴露给浏览器）。
"""

from .catalog import ToolCatalog
from .manager import MCPClientManager, ToolExecutionContext
from .provider import InProcessProvider

__all__ = [
    "InProcessProvider",
    "MCPClientManager",
    "ToolCatalog",
    "ToolExecutionContext",
]
