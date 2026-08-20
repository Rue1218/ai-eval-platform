"""MCP 工具中心路由（API V1.3 §3.6.1）。

V1.0 仅暴露内置受控短工具清单的只读视图；外部 MCP Server 的接入、
探活、解绑与动态发现均不在本期范围，浏览器侧对应按钮展示能力未启用。
"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..models import User
from ..schemas import McpToolOut

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# 内置短工具清单：与 Agent Host 实际绑定保持一致，长任务一律走 task.create 入队
BUILTIN_TOOLS: list[McpToolOut] = [
    McpToolOut(name="model.list", desc="查询可用被测协议档与模型清单", permission="read", enabled=True),
    McpToolOut(name="task.get", desc="查询任务状态与进度", permission="read", enabled=True),
    McpToolOut(name="task.create", desc="按确认卡 TaskSpec 创建任务并入队", permission="write", enabled=True),
    McpToolOut(name="task.cancel", desc="请求取消排队中或运行中的任务", permission="write", enabled=True),
    McpToolOut(name="dispatch.overview", desc="读取调度大盘与 Worker 节点池状态", permission="read", enabled=True),
    McpToolOut(name="dataset.list", desc="查询数据集版本和行数", permission="read", enabled=True),
    McpToolOut(name="report.get", desc="按 report_id 读取评测报告与指标快照", permission="read", enabled=True),
    McpToolOut(name="kb.list", desc="查询知识库与黄金 QA 资产", permission="read", enabled=True),
    McpToolOut(name="testcase.confirm", desc="确认用例入库", permission="write", enabled=True),
    McpToolOut(
        name="audio.voiceclone",
        desc="把文本合成语音；附 wav/mp3 时克隆该音色，否则用内置音色",
        permission="write",
        enabled=True,
    ),
]

# 独立 MCP 注册项：仅供管理页展示，未挂载到 Eval-Core，不得被 Agent 当作内置工具执行
UNMOUNTED_TOOLS: list[McpToolOut] = [
    McpToolOut(
        name="image.generate",
        desc="Qwen Image 3.0 文本或参考图生图（独立 stdio MCP，当前未挂载）",
        permission="write",
        enabled=False,
        source="standalone",
    ),
]

MCP_TOOL_REGISTRY: list[McpToolOut] = [*BUILTIN_TOOLS, *UNMOUNTED_TOOLS]


@router.get("/tools", summary="MCP 工具注册清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """返回内置短工具与未挂载独立 MCP 注册项及权限级别。"""
    return {"items": [t.model_dump(mode="json") for t in MCP_TOOL_REGISTRY], "total": len(MCP_TOOL_REGISTRY)}
