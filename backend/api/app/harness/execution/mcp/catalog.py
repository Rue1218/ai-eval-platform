"""内部 MCP 目录（阶段 D，P3）：平台 allowlist 工具的唯一目录/风险/策略来源。

``ToolCatalog`` 从 ``ToolRegistry`` 投影 ``ToolDescriptor``，提供 tool_id 与
短名双索引；工具名冲突（同短名跨 server）与 tool_id 重复在登记时即拒绝
（VALIDATION）。目录只含可序列化描述符，不含 handler。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolDescriptor

from ..registry import ToolRegistry

# 工具短名 → 默认 server 归属（未显式声明 server_id 时的兜底；平台工具都应
# 显式声明 server_id，此处仅防御漏挂导致目录缺 server）。
_SERVER_INFERENCE: Mapping[str, str] = {
    "read": "platform.files",
    "write": "platform.files",
    "edit": "platform.files",
    "web_search": "platform.web",
    "web_fetch": "platform.web",
    "bash": "platform.sandbox",
}
_FALLBACK_SERVER = "platform.custom"


class ToolCatalog:
    """内部工具目录：tool_id 与短名双索引；名称冲突在登记时拒绝。"""

    def __init__(self) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._by_name: dict[str, str] = {}

    @classmethod
    def build(cls, registry: ToolRegistry) -> ToolCatalog:
        """从注册表构建目录（含 server 推断与冲突校验）。"""
        catalog = cls()
        catalog.refresh(registry)
        return catalog

    def refresh(self, registry: ToolRegistry) -> None:
        """重建目录；注册表新增工具后调用即可反映。冲突立即拒绝。"""
        self._descriptors.clear()
        self._by_name.clear()
        for definition in registry.iter_defs():
            self.add(definition.to_descriptor())

    def add(self, descriptor: ToolDescriptor) -> None:
        """登记一个描述符；tool_id 重复或短名跨 server 冲突抛 VALIDATION。

        ``tool_id`` 以 ``ToolDef.tool_id`` 为准（保持与工具调用侧一致）；未
        声明 server_id 时仅补 server 归属用于分组，不改动 tool_id。
        """
        if not descriptor.server_id:
            descriptor = replace(
                descriptor,
                server_id=_SERVER_INFERENCE.get(descriptor.name, _FALLBACK_SERVER),
            )
        tool_id = descriptor.tool_id
        if tool_id in self._descriptors:
            raise AppError(ErrorCode.VALIDATION, f"目录工具重复：{tool_id}")
        existing = self._by_name.get(descriptor.name)
        if existing is not None and existing != tool_id:
            raise AppError(
                ErrorCode.VALIDATION,
                f"工具短名冲突：{descriptor.name} 已属于 {existing}",
            )
        self._descriptors[tool_id] = descriptor
        self._by_name[descriptor.name] = tool_id

    def all_descriptors(self) -> tuple[ToolDescriptor, ...]:
        """全部目录描述符（可序列化，供 /api/mcp/tools 投影）。"""
        return tuple(self._descriptors.values())

    def get(self, tool_id: str) -> ToolDescriptor | None:
        """按 tool_id 查描述符；未登记返回 None。"""
        return self._descriptors.get(tool_id)

    def resolve_name(self, short_name: str) -> str | None:
        """短名 → tool_id；未登记返回 None。"""
        return self._by_name.get(short_name)

    def servers(self) -> tuple[str, ...]:
        """已登记 server 分组（排序，供前端分组展示）。"""
        return tuple(sorted({descriptor.server_id for descriptor in self._descriptors.values()}))
