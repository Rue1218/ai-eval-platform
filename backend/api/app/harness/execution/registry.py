"""Harness 执行层：工具注册表（M5 阶段 2，EX-1/EX-5）。

工具元数据、白名单与执行分派的**唯一来源**：新增工具必须登记并走统一执行
入口；未注册工具调用一律拒绝（VALIDATION），禁止假成功。``ToolDef.handler``
为运行时执行函数（不入 GraphState，仅注册表持有）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.errors import AppError, ErrorCode


@dataclass(frozen=True, slots=True)
class ToolDef:
    """工具元数据（注册表唯一源）。"""

    name: str  # 如 "read"/"web_search"
    description: str
    parameters_schema: Mapping[str, object]  # JSON schema
    permission: str  # 权限标识
    timeout_s: float  # 执行超时
    handler: Callable[..., object]  # 执行函数（不入 GraphState，仅运行时）


class ToolRegistry:
    """工具注册表；白名单与分派唯一源。"""

    def __init__(self) -> None:
        self._defs: dict[str, ToolDef] = {}

    def register(self, def_: ToolDef) -> None:
        """登记工具；重名登记抛 VALIDATION（防止覆盖导致分派漂移）。"""
        if def_.name in self._defs:
            raise AppError(ErrorCode.VALIDATION, f"工具已登记：{def_.name}")
        self._defs[def_.name] = def_

    def get(self, name: str) -> ToolDef:
        """取定义；未注册抛 AppError(VALIDATION)。"""
        definition = self._defs.get(name)
        if definition is None:
            raise AppError(ErrorCode.VALIDATION, f"工具未注册：{name}")
        return definition

    def all_defs(self) -> list[Mapping[str, object]]:
        """返回全部工具定义（可序列化投影，供 M2 select_tool_defs 最小注入）。

        只含元数据，不含 handler（handler 为运行时 Callable，不可序列化）。
        """
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters_schema": dict(definition.parameters_schema),
                "permission": definition.permission,
                "timeout_s": definition.timeout_s,
            }
            for definition in self._defs.values()
        ]

    def get_def(self, name: str) -> Mapping[str, object] | None:
        """按名取可序列化定义（M2 select_tool_defs 消费）；未注册返回 None。"""
        definition = self._defs.get(name)
        if definition is None:
            return None
        return {
            "name": definition.name,
            "description": definition.description,
            "parameters_schema": dict(definition.parameters_schema),
            "permission": definition.permission,
            "timeout_s": definition.timeout_s,
        }

    def is_registered(self, name: str) -> bool:
        """是否已登记。"""
        return name in self._defs


def build_default_registry() -> ToolRegistry:
    """阶段 3 默认注册（基础工具 + 沙箱 bash）。

    注册 read/write/edit/web_search/web_fetch/bash；bash 在一次性 bwrap 沙箱内
    执行（无网络、工作区唯一可写、资源受限、超时整树清理），黑名单为纵深防御
    （M5 §3.8.4 阶段 3 闭环），bwrap 不可用时 fail-closed 拒绝。
    """
    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="read",
            description="读取沙箱目录内的文本文件（相对路径）；单次最多返回 20000 字符，文件未读完会附带截断标记和 offset 提示，请按提示继续分段读取",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对路径"},
                    "offset": {"type": "integer", "description": "起始字符偏移，默认 0", "minimum": 0},
                    "limit": {"type": "integer", "description": "最多返回字符数，默认 20000", "minimum": 1},
                },
                "required": ["path"],
            },
            permission="sandbox.read",
            timeout_s=10.0,
            handler=_read_handler,
        )
    )
    registry.register(
        ToolDef(
            name="write",
            description="在沙箱目录内新建文本文件（相对路径）",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            permission="sandbox.write",
            timeout_s=10.0,
            handler=_write_handler,
        )
    )
    registry.register(
        ToolDef(
            name="edit",
            description="在沙箱目录内编辑文本文件（原子替换）",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
            permission="sandbox.write",
            timeout_s=10.0,
            handler=_edit_handler,
        )
    )
    registry.register(
        ToolDef(
            name="web_search",
            description="内部搜索引擎检索（平台自实现适配器，不走外部 MCP）",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
            permission="web.search",
            timeout_s=15.0,
            handler=_web_search_handler,
        )
    )
    registry.register(
        ToolDef(
            name="web_fetch",
            description="内部网页抓取（平台自实现适配器 + 脱敏，不走外部 MCP）",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
            permission="web.fetch",
            timeout_s=15.0,
            handler=_web_fetch_handler,
        )
    )
    registry.register(
        ToolDef(
            name="bash",
            description="在 bwrap 沙箱内执行 shell 命令（相对路径、无网络、受资源限制）",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
            permission="sandbox.bash",
            timeout_s=15.0,
            handler=_bash_handler,
        )
    )
    return registry


def _read_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> str:
    """read 工具 handler：受控目录内读取相对路径（防目录穿越）。

    ``sandbox_dir`` 由平台经 dispatch 注入，**禁止模型传参**（M5-D7 红线）；
    ``offset``/``limit`` 支持长文本分段读取。
    """
    from .dispatch import read_file_safe

    return read_file_safe(
        str(arguments.get("path", "")),
        sandbox_dir or "",
        offset=arguments.get("offset"),
        limit=arguments.get("limit"),
    )


def _write_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> str:
    """write 工具 handler：受控目录内写入相对路径（防目录穿越）。"""
    from .dispatch import write_file_safe

    write_file_safe(
        str(arguments.get("path", "")),
        str(arguments.get("content", "")),
        sandbox_dir or "",
    )
    return "写入完成"


def _edit_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> str:
    """edit 工具 handler：受控目录内原子替换（防目录穿越）。"""
    from .dispatch import edit_file_safe

    edit_file_safe(
        str(arguments.get("path", "")),
        str(arguments.get("old", "")),
        str(arguments.get("new", "")),
        sandbox_dir or "",
    )
    return "编辑完成"


def _web_search_handler(arguments: Mapping[str, object], _sandbox_dir: str | None = None) -> str:
    """web_search 工具 handler：内部短 MCP 适配器（不走外部 MCP 服务器）。"""
    from .dispatch import web_search

    return web_search(str(arguments.get("query", "")), timeout_s=15.0)


def _web_fetch_handler(arguments: Mapping[str, object], _sandbox_dir: str | None = None) -> str:
    """web_fetch 工具 handler：内部抓取适配器 + 脱敏（不走外部 MCP 服务器）。"""
    from .dispatch import web_fetch

    return web_fetch(str(arguments.get("url", "")), timeout_s=15.0)


def _bash_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> str:
    """bash 工具 handler：bwrap 沙箱内执行（阶段 3 开放通用 bash）。

    资源限制读 Settings（内存/进程数/CPU），``sandbox_dir`` 由平台注入，
    禁止模型传参（M5-D7 红线）；引擎为 "off" 或 bwrap 不可用时 fail-closed
    （VALIDATION），禁止降级为裸 subprocess。
    """
    from app.config import settings
    from app.harness.execution.dispatch import run_bash
    from app.harness.execution.sandbox import SandboxLimits

    if settings.sandbox_engine != "bwrap":
        raise AppError(ErrorCode.VALIDATION, "沙箱引擎未启用")
    limits = SandboxLimits(
        memory_kb=settings.sandbox_memory_mb * 1024,
        nproc=settings.sandbox_nproc,
        cpu_s=settings.sandbox_cpu_s,
    )
    return run_bash(
        str(arguments.get("command", "")),
        sandbox_dir=sandbox_dir or "",
        timeout_s=15.0,
        limits=limits,
    )
