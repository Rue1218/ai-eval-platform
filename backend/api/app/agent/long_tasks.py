"""长任务工具门禁：Agent 进程只允许短 MCP，禁止同步跑评测 / RAG / 压测。"""

from ..errors import AppError, ErrorCode
from .log import agent_trace

# Worker 专用长工具，出现在 Agent tools_needed 或 _call_tool 时必须抛错
LONG_MCP_TOOLS = frozenset(
    {
        "benchmark.run",
        "rag.evaluate",
        "testcase.generate",
        "stress.run",
    }
)


def assert_short_tool(name: str) -> None:
    """校验工具名可在 Agent 同步调用；长工具抛 ``VALIDATION``。"""
    try:
        tool = (name or "").strip()
        if not tool:
            raise AppError(ErrorCode.VALIDATION, "工具名不能为空")
        if tool in LONG_MCP_TOOLS:
            agent_trace(f"拒绝在对话进程执行长工具 name={tool}")
            raise AppError(
                ErrorCode.VALIDATION,
                f"「{tool}」是长任务，只能入队后由 Worker 执行",
                fields={"tool": tool, "feature": "long_mcp"},
            )
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"短工具校验内部异常: {type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "工具校验失败") from exc
