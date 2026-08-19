"""Agent Host 辅助包：控制台追踪、长工具门禁、LightRAG 占位（M3 再接真查询）。"""

from .lightrag_stub import assert_lightrag_ready, query_lightrag
from .log import agent_trace
from .long_tasks import LONG_MCP_TOOLS, assert_short_tool

__all__ = [
    "LONG_MCP_TOOLS",
    "agent_trace",
    "assert_lightrag_ready",
    "assert_short_tool",
    "query_lightrag",
]
