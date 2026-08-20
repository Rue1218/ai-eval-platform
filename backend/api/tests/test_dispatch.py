"""调度中心与 MCP 工具中心路由单测（不依赖数据库连接）。

未携带登录 Cookie 的请求在依赖注入阶段即被 401 拒绝，
不会触达 SQLAlchemy 查询，因此可在无数据库环境运行。
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.routers.mcp import MCP_TOOL_REGISTRY
from app.schemas import DispatchConfigUpdate, DispatchWorkerCreate, DispatchWorkerUpdate


@pytest.mark.parametrize(
    "path",
    [
        "/api/dispatch/overview",
        "/api/dispatch/workers",
        "/api/dispatch/events",
        "/api/mcp/tools",
    ],
)
def test_dispatch_and_mcp_require_auth(path: str):
    # 未登录访问调度 / MCP 只读端点应统一返回 401 + UNAUTHORIZED
    client = TestClient(app)
    resp = client.get(path)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_worker_create_schema_defaults():
    # 注册节点默认权重 100、能力标签为空列表
    body = DispatchWorkerCreate(id="worker-01", name="GPU-Node-A1")
    assert body.weight == 100
    assert body.caps == []


def test_worker_create_rejects_bad_weight():
    with pytest.raises(ValidationError):
        DispatchWorkerCreate(id="w", name="n", weight=0)


def test_worker_update_state_enum():
    # 节点治理仅接受契约约定的四种状态
    assert DispatchWorkerUpdate(state="draining").state == "draining"
    with pytest.raises(ValidationError):
        DispatchWorkerUpdate(state="paused")


def test_dispatch_config_strategy_enum():
    assert DispatchConfigUpdate(strategy="亲和性").strategy == "亲和性"
    with pytest.raises(ValidationError):
        DispatchConfigUpdate(strategy="随机分配")


def test_mcp_registry_exposes_mounted_qwen_image_tool():
    """Qwen Image 通过内部 mcp_tools 执行，并在管理页标记为已挂载。"""
    tool = next(item for item in MCP_TOOL_REGISTRY if item.name == "image.generate")
    assert tool.permission == "write"
    assert tool.enabled is True
    assert tool.source == "builtin"
