"""Agent Worker 只读目录（混合引擎 H1，API.md §3.6.3）。

返回 H0 静态 ``AgentRegistry`` 的脱敏投影：仅描述同一 LangGraph 图内的
工具视野与能力边界，不代表模型正在调用；不含 API Key、协议客户端或 LLM
实例。注册表内容为部署级静态声明（启动期已通过 strict 校验），端点内直接
构建投影，不持有可变状态、不触碰数据库。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..harness.orchestration.agents import get_default_agent_registry
from ..models import User

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", summary="Agent Worker 只读目录（静态注册表投影，不代表正在调用）")
def list_agents(user: User = Depends(get_current_user)) -> dict:
    """列出全部静态 Worker 及其能力、工具视野与预算上限（脱敏投影）。"""
    agents = [
        {
            "agent_id": definition.agent_id,
            "display_name": definition.display_name,
            "capabilities": sorted(definition.capabilities),
            "allowed_tools": list(definition.allowed_tools),
            "skill_ids": list(definition.skill_ids),
            "max_permission": definition.max_permission,
            "budget": dict(definition.budget),
            "model_profile_id": definition.model_profile_id,
            "description": definition.description,
        }
        for definition in get_default_agent_registry().iter_defs()
    ]
    return {"agents": agents}
