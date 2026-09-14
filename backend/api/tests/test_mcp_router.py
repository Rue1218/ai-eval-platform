import pytest

from app.models import User
from app.routers import mcp as mcp_router
from app.routers.mcp import list_all_tools


def test_list_all_tools_returns_native_and_mcp():
    user = User(id="u-admin", username="admin", role="admin")
    res = list_all_tools(user=user)
    assert "items" in res
    assert len(res["items"]) >= 10
    read_tool = next(item for item in res["items"] if item["name"] == "read")
    assert "parameters_schema" in read_tool
    assert "output_schema" in read_tool
    assert "code_details" in read_tool
    assert read_tool["code_details"]["source_file"]
    # code_snippet 已移除：原为手写示意代码且与真实 handler 不符（伪造展示）
    assert "code_snippet" not in read_tool["code_details"]


@pytest.mark.asyncio
async def test_health_check_returns_channel_statuses(monkeypatch):
    """默认关闭外部媒体服务时，基础工具和内部 MCP 健康检查保持可复现。"""
    monkeypatch.setattr(mcp_router.settings, "media_mcp_enabled", False)
    monkeypatch.setattr(mcp_router, "_catalog", None)
    user = User(id="u-admin", username="admin", role="admin")

    res = await mcp_router.health_check(user=user)

    assert res["ok"] is True
    assert "native" in res["channels"]
    assert "internal_mcp" in res["channels"]
    assert "external_gateway" in res["channels"]


@pytest.mark.asyncio
async def test_health_check_discovers_enabled_media_tools(monkeypatch):
    """已启用时执行目录发现，不调用任何计费媒体工具。"""

    class Provider:
        """以确定结果替代网络服务，只验证健康检查的协议边界。"""

        def __init__(self, endpoint, *, request_timeout_s):
            self.endpoint = endpoint
            self.request_timeout_s = request_timeout_s

        async def list_tools(self):
            return ("image.generate", "video.create", "video.status")

    monkeypatch.setattr(mcp_router.settings, "media_mcp_enabled", True)
    monkeypatch.setattr(mcp_router, "StreamableHttpProvider", Provider)
    monkeypatch.setattr(mcp_router, "_catalog", None)
    user = User(id="u-admin", username="admin", role="admin")

    res = await mcp_router.health_check(user=user)

    assert res["ok"] is True
    assert res["channels"]["external_gateway"]["status"] == "connected"
    assert res["channels"]["external_gateway"]["tools"] == [
        "image.generate", "video.create", "video.status"
    ]
