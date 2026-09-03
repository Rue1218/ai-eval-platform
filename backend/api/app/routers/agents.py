"""Agent Registry 只读目录（H1，对应 API.md 新增 `GET /api/agents`）。

返回 ``AgentRegistry`` 全部 Worker 的能力元数据（agent_id / display_name /
capabilities / allowed_tools / max_permission / description），只读、脱敏——
仅暴露协议档 ID，不暴露任何密钥或配置值。与 ``/api/mcp/*`` 工具目录同源
展示原则：H1 阶段这些 Worker 表示已注册的基础设施，不代表模型正在派发
子代理（discover 与 ToolNode 在 H3 恢复）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..harness.orchestration.agents import build_default_agent_registry
from ..models import User

router = APIRouter(prefix="/api/agents", tags=["agent-registry"])


@router.get("", summary="Worker 能力目录（只读）")
def list_agents(user: User = Depends(get_current_user)):
    """返回 AgentRegistry 全部 Worker 的只读能力描述。

    响应结构（API.md）：``{"items": [{agent_id, display_name, capabilities,
    allowed_tools, max_permission, model_profile_id, description}]}``。
    """
    _ = user
    registry = build_default_agent_registry()
    return {
        "items": [
            {
                "agent_id": definition.agent_id,
                "display_name": definition.display_name,
                "capabilities": sorted(definition.capabilities),
                "allowed_tools": list(definition.allowed_tools),
                "max_permission": definition.max_permission,
                "model_profile_id": definition.model_profile_id,
                "description": definition.description,
            }
            for definition in registry.iter_defs()
        ]
    }
