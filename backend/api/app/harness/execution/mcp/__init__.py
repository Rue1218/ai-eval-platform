"""内部 MCP 扩展 Host（阶段 D，P3）。

``catalog``（显式 MCP 扩展目录：目录/风险/策略唯一源）→ ``provider``
（in-process 包装注册表 handler）→ ``manager``（``MCPClientManager``：
tools/list + tools/call + 超时/取消/错误归一）。

仅连接平台部署、审计、允许列表内的受控扩展：``platform.tasks`` 走进程内
provider，``media.generation`` 走固定 Compose 私网的 Streamable HTTP provider。
read/write/bash/web 与对话拆解 task 等基础能力仍走 NativeToolExecutor；浏览器
不可直接调用 ``tools/call`` 或指定任意外部 MCP 地址。
"""

from .catalog import ToolCatalog
from .manager import MCPClientManager, ToolExecutionContext
from .metrics import ToolMetrics, get_default_metrics
from .provider import InProcessProvider
from .streamable_provider import StreamableHttpProvider

__all__ = [
    "InProcessProvider",
    "MCPClientManager",
    "StreamableHttpProvider",
    "ToolCatalog",
    "ToolExecutionContext",
    "ToolMetrics",
    "get_default_metrics",
]
