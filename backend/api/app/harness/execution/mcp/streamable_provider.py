"""受控 Streamable HTTP MCP provider。

媒体服务部署在 Compose 私网，API 只把已经过目录和权限门禁的工具调用转发给它。
此层不持有模型上游凭据，也不会记录 MCP 返回的原文或连接异常详情。
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.harness.contracts import ToolResult

from ..registry_schema import validate_tool_output


class StreamableHttpProvider:
    """按调用建立短会话的 Streamable HTTP MCP 客户端。

    媒体生图可能持续数十秒，因此连接超时由 provider 配置控制；实际工具总时限
    仍由 ``MCPClientManager`` 依据目录中的 ``ToolDef.timeout_s`` 统一裁决。
    """

    def __init__(self, endpoint: str, *, request_timeout_s: float) -> None:
        """校验受控服务地址，拒绝用户名、查询串和非 HTTP(S) 形式。"""
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or request_timeout_s <= 0
        ):
            raise ValueError("Streamable HTTP MCP 地址或超时配置非法")
        self._endpoint = endpoint.rstrip("/")
        self._request_timeout_s = request_timeout_s

    async def invoke(
        self,
        *,
        tool_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        output_schema: Mapping[str, object],
        call_id: str,
    ) -> ToolResult:
        """完成 initialize 与一次 tools/call，并把外部错误归一为安全结果。"""
        try:
            async with streamablehttp_client(
                self._endpoint,
                timeout=self._request_timeout_s,
                sse_read_timeout=self._request_timeout_s,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=dict(arguments))
        except Exception:  # noqa: BLE001 —— 不向模型或浏览器泄漏远端连接细节
            return ToolResult(
                name=tool_name,
                ok=False,
                error={"code": "UPSTREAM", "message": "媒体 MCP 服务不可用"},
                call_id=call_id,
            )
        if result.isError:
            return ToolResult(
                name=tool_name,
                ok=False,
                error={"code": "UPSTREAM", "message": "媒体 MCP 调用失败"},
                call_id=call_id,
            )
        payload = result.structuredContent
        if not isinstance(payload, Mapping):
            return ToolResult(
                name=tool_name,
                ok=False,
                error={"code": "UPSTREAM", "message": "媒体 MCP 未返回结构化结果"},
                call_id=call_id,
            )
        data = dict(payload)
        # image.generate 的失败由媒体服务以结构化错误返回；视频任务本身的
        # ``FAILED`` 是查询成功后的业务状态，仍需交给 Agent 解释，不能混淆。
        if data.get("status") == "failed":
            return ToolResult(
                name=tool_name,
                ok=False,
                error={"code": "UPSTREAM", "message": "媒体 MCP 调用失败"},
                call_id=call_id,
            )
        schema_error = validate_tool_output(output_schema, data)
        if schema_error:
            return ToolResult(
                name=tool_name,
                ok=False,
                error={"code": "UPSTREAM", "message": "媒体 MCP 返回不符合工具契约"},
                call_id=call_id,
            )
        return ToolResult(name=tool_name, ok=True, data=data, call_id=call_id)

    async def list_tools(self) -> tuple[str, ...]:
        """仅用于管理端健康检查，发现远程目录但不执行任何计费工具。"""
        try:
            async with streamablehttp_client(
                self._endpoint,
                timeout=self._request_timeout_s,
                sse_read_timeout=self._request_timeout_s,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
        except Exception:  # noqa: BLE001 —— 健康接口同样不回显远端细节
            return ()
        return tuple(tool.name for tool in result.tools)
