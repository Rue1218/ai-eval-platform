"""Streamable HTTP 协议烟测：只验证 MCP 生命周期和目录，不触发计费调用。"""

from __future__ import annotations

import importlib
import sys

from starlette.testclient import TestClient


def test_streamable_http_initializes_and_lists_media_tools(monkeypatch) -> None:
    """客户端完成 initialize 后可发现固定的三个媒体工具。"""
    monkeypatch.setenv(
        "MEDIA_MCP_COMPATIBLE_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("MEDIA_MCP_API_KEY", "test-key")
    sys.modules.pop("app.server", None)
    module = importlib.import_module("app.server")
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    try:
        with TestClient(module.app) as client:
            initialized = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "media-mcp-test", "version": "1"},
                    },
                },
            )
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]
            request_headers = {
                **headers,
                "MCP-Session-Id": session_id,
                "MCP-Protocol-Version": "2025-11-25",
            }
            ready = client.post(
                "/mcp", headers=request_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            listed = client.post(
                "/mcp", headers=request_headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
        assert ready.status_code == 202
        assert listed.status_code == 200
        assert [item["name"] for item in listed.json()["result"]["tools"]] == [
            "image.generate", "video.create", "video.status"
        ]
    finally:
        sys.modules.pop("app.server", None)
