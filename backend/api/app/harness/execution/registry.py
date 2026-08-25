"""Harness 执行层：工具注册表（M5 阶段 2，EX-1/EX-5）。

工具元数据、白名单与执行分派的**唯一来源**：新增工具必须登记并走统一执行
入口；未注册工具调用一律拒绝（VALIDATION），禁止假成功。``ToolDef.handler``
为运行时执行函数（不入 GraphState，仅注册表持有）。基础文件、网络、沙箱与
任务拆解工具固定为 ``transport=native``；只有评测/RAG 等后续扩展工具才允许
显式标记为 ``transport=mcp`` 并投影到内部 MCP 目录。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolDescriptor

# 工具参数只接受平台已实现、可本地确定解释的 JSON Schema 子集。新增 MCP 工具
# 不得静默携带未校验的组合/引用规则；需要扩展时先实现校验语义并补测试。
_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "items",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
    }
)
_SUPPORTED_JSON_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)


@dataclass(frozen=True, slots=True)
class ToolDef:
    """工具元数据（注册表唯一源）。

    ``transport`` 决定执行边界：原生工具由 ``NativeToolExecutor`` 直连 handler；
    MCP 工具才由 ``MCPClientManager`` 通过受控目录调用。``server_id`` 与
    ``tool_id`` 仅对 MCP 工具有路由含义，模型参数中不得携带。
    """

    name: str  # 如 "read"/"web_search"
    description: str
    parameters_schema: Mapping[str, object]  # JSON schema
    permission: str  # 权限标识
    timeout_s: float  # 执行超时
    handler: Callable[..., object]  # 执行函数（不入 GraphState，仅运行时）
    transport: Literal["native", "mcp"] = "native"  # 执行通道
    server_id: str = ""  # 如 "platform.files"（空则目录按名称推断归属）
    display_name: str = ""  # 如 "读取文件"
    risk_level: Literal["read", "modify", "network", "code", "long"] = "read"
    execution_mode: Literal["short", "long"] = "short"
    requires_confirmation: bool = False
    supports_streaming: bool = False

    @property
    def tool_id(self) -> str:
        """内部目录唯一 ID：``{server_id}.{name}``；空 server 回退短名。"""
        return f"{self.server_id}.{self.name}" if self.server_id else self.name

    def to_descriptor(self) -> ToolDescriptor:
        """投影为可序列化描述符（MCP 目录 / 风险 / 策略唯一源，不含 handler）。"""
        return ToolDescriptor(
            tool_id=self.tool_id,
            server_id=self.server_id,
            name=self.name,
            display_name=self.display_name or self.name,
            description=self.description,
            input_schema=dict(self.parameters_schema),
            permission=self.permission,
            risk_level=self.risk_level,
            execution_mode=self.execution_mode,
            timeout_s=float(self.timeout_s),
            requires_confirmation=self.requires_confirmation,
            supports_streaming=self.supports_streaming,
        )


class ToolRegistry:
    """工具注册表；白名单与分派唯一源。"""

    def __init__(self) -> None:
        self._defs: dict[str, ToolDef] = {}

    def register(self, def_: ToolDef) -> None:
        """登记工具；重名登记抛 VALIDATION（防止覆盖导致分派漂移）。"""
        if def_.name in self._defs:
            raise AppError(ErrorCode.VALIDATION, f"工具已登记：{def_.name}")
        schema_error = validate_tool_schema(def_.parameters_schema)
        if schema_error:
            raise AppError(ErrorCode.VALIDATION, f"工具参数 Schema 无效：{schema_error}")
        self._defs[def_.name] = def_

    def get(self, name: str) -> ToolDef:
        """取定义；未注册抛 AppError(VALIDATION)。"""
        definition = self.find(name)
        if definition is None:
            raise AppError(ErrorCode.VALIDATION, f"工具未注册：{name}")
        return definition

    def find(self, name: str) -> ToolDef | None:
        """按名称查询运行时定义；未注册返回 ``None``。"""
        return self._defs.get(name)

    def names(self) -> tuple[str, ...]:
        """返回已登记工具名，供 Gate 构造白名单。"""
        return tuple(self._defs)

    def iter_defs(self, *, transport: Literal["native", "mcp"] | None = None) -> Iterator[ToolDef]:
        """返回底层 ``ToolDef`` 对象（含 handler，限执行层内部消费）。

        ``transport`` 非空时只返回指定执行通道，供 MCP 目录和 provider 排除
        原生基础工具；对外可序列化投影仍走 ``all_defs``/``get_def``，避免
        handler 泄漏到模型或前端。
        """
        definitions = self._defs.values()
        if transport is None:
            return iter(definitions)
        return (definition for definition in definitions if definition.transport == transport)

    def has_transport(self, transport: Literal["native", "mcp"]) -> bool:
        """判断是否存在指定执行通道的工具，避免空 MCP Host 的构建开销。"""
        return any(definition.transport == transport for definition in self._defs.values())

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
        definition = self.find(name)
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


def required_parameter_names(schema: Mapping[str, object]) -> tuple[str, ...]:
    """提取工具 JSON Schema 的必填参数名，供既有 Gate 保持同一事实来源。

    完整的类型与范围校验由 ``validate_tool_arguments`` 完成；这里仅向既有
    Gate 提供必填字段投影，避免工具注册表与门禁各自维护一份 required 列表。
    """
    required = schema.get("required")
    if not isinstance(required, list | tuple):
        return ()
    return tuple(str(name) for name in required if isinstance(name, str) and name)


def validate_tool_schema(schema: Mapping[str, object]) -> str | None:
    """在注册期拒绝执行器尚未实现语义的 JSON Schema 关键字。"""
    return _validate_schema_definition(schema, "arguments")


def _validate_schema_definition(schema: Mapping[str, object], path: str) -> str | None:
    """递归验证 Schema 子集本身，避免运行时对未知规则静默放行。"""
    unsupported = sorted(str(key) for key in schema if key not in _SUPPORTED_SCHEMA_KEYWORDS)
    if unsupported:
        return f"{path} 包含不支持的关键字：{', '.join(unsupported)}"

    expected = schema.get("type")
    expected_types = (expected,) if isinstance(expected, str) else expected
    if expected is not None:
        if not isinstance(expected_types, list | tuple) or not expected_types:
            return f"{path}.type 必须是受支持的类型或非空类型列表"
        invalid_types = [str(item) for item in expected_types if item not in _SUPPORTED_JSON_TYPES]
        if invalid_types:
            return f"{path}.type 包含不支持的类型：{', '.join(invalid_types)}"

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            return f"{path}.properties 必须是对象"
        for key, child in properties.items():
            if not isinstance(key, str) or not key:
                return f"{path}.properties 包含无效参数名"
            if not isinstance(child, Mapping):
                return f"{path}.{key} 必须是 Schema 对象"
            error = _validate_schema_definition(child, f"{path}.{key}")
            if error:
                return error

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list | tuple) or any(
            not isinstance(name, str) or not name for name in required
        ):
            return f"{path}.required 必须是非空字符串列表"
        if len(set(required)) != len(required):
            return f"{path}.required 不能包含重复参数"

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        return f"{path}.additionalProperties 仅支持布尔值"

    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list | tuple):
        return f"{path}.enum 必须是数组"

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, Mapping):
            return f"{path}.items 必须是 Schema 对象"
        error = _validate_schema_definition(items, f"{path}.items")
        if error:
            return error

    for key in ("minLength", "maxLength"):
        value = schema.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return f"{path}.{key} 必须是非负整数"
    min_length = schema.get("minLength")
    max_length = schema.get("maxLength")
    if isinstance(min_length, int) and isinstance(max_length, int) and min_length > max_length:
        return f"{path}.minLength 不能大于 maxLength"

    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            return f"{path}.pattern 必须是字符串"
        try:
            re.compile(pattern)
        except re.error:
            return f"{path}.pattern 不是有效正则表达式"

    for key in ("minimum", "maximum"):
        value = schema.get(key)
        if value is not None and (
            not isinstance(value, int | float) or isinstance(value, bool)
        ):
            return f"{path}.{key} 必须是数字"
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if (
        isinstance(minimum, int | float)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int | float)
        and not isinstance(maximum, bool)
        and minimum > maximum
    ):
        return f"{path}.minimum 不能大于 maximum"
    return None


def validate_tool_arguments(schema: Mapping[str, object], arguments: Mapping[str, object]) -> str | None:
    """校验内部工具使用的受限 JSON Schema，失败返回脱敏中文原因。

    平台工具当前只需要 object/properties/required、基础标量类型、枚举和范围
    约束。校验器刻意不执行 schema 中的任意代码，也不支持远程 ``$ref``，从而
    保证模型参数只能在 ToolNode 的受控本地边界内被解释。
    """
    return _validate_schema_value(arguments, schema, "arguments")


def _validate_schema_value(value: object, schema: Mapping[str, object], path: str) -> str | None:
    """递归校验一个 JSON 值，覆盖内部短工具声明的安全子集。"""
    expected = schema.get("type")
    expected_types = (expected,) if isinstance(expected, str) else expected
    if isinstance(expected_types, list | tuple) and expected_types:
        if not any(_matches_json_type(value, str(item)) for item in expected_types):
            labels = "/".join(str(item) for item in expected_types)
            return f"参数 {path} 类型无效，应为 {labels}"

    enum = schema.get("enum")
    if isinstance(enum, list | tuple) and value not in enum:
        return f"参数 {path} 不在允许范围内"

    if isinstance(value, Mapping):
        required = required_parameter_names(schema)
        missing = [name for name in required if name not in value]
        if missing:
            return f"缺少必填参数：{', '.join(missing)}"
        properties = schema.get("properties")
        properties_map = properties if isinstance(properties, Mapping) else {}
        if schema.get("additionalProperties") is False:
            unexpected = [str(key) for key in value if key not in properties_map]
            if unexpected:
                return f"包含未允许的参数：{', '.join(unexpected)}"
        for key, child in value.items():
            child_schema = properties_map.get(key)
            if not isinstance(child_schema, Mapping):
                continue
            error = _validate_schema_value(child, child_schema, str(key))
            if error:
                return error

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, child in enumerate(value):
                error = _validate_schema_value(child, item_schema, f"{path}[{index}]")
                if error:
                    return error

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return f"参数 {path} 长度不能小于 {min_length}"
        if isinstance(max_length, int) and len(value) > max_length:
            return f"参数 {path} 长度不能大于 {max_length}"
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.search(pattern, value):
            return f"参数 {path} 格式无效"

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            return f"参数 {path} 不能小于 {minimum}"
        if isinstance(maximum, int | float) and value > maximum:
            return f"参数 {path} 不能大于 {maximum}"
    return None


def _matches_json_type(value: object, expected: str) -> bool:
    """避免 Python ``bool`` 被误判为 JSON integer。"""
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def build_default_registry() -> ToolRegistry:
    """注册默认原生基础工具（文件、网络、沙箱与任务拆解）。

    注册 read/write/edit/web_search/web_fetch/bash/task。它们经原生 ToolCall
    直连执行，不进入 MCP 目录；bash 仍在一次性 bwrap 沙箱内执行（无网络、
    工作区唯一可写、资源受限、超时整树清理），引擎不可用时 fail-closed。
    """
    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="read",
            description="按行读取沙箱目录内的文本文件（相对路径）；offset/limit 均为 0-based 行，单次最多 2000 行和 120000 字符。结果会返回下一页 next_offset；优先基于已读片段总结，仅在确有必要时继续读取。",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "相对路径"},
                    "offset": {"type": "integer", "description": "起始行号，0-based，默认 0", "minimum": 0},
                    "limit": {"type": "integer", "description": "最多读取行数，默认/上限 2000", "minimum": 1, "maximum": 2000},
                },
                "required": ["path"],
            },
            permission="sandbox.read",
            timeout_s=10.0,
            handler=_read_handler,
            display_name="读取文件",
            risk_level="read",
        )
    )
    registry.register(
        ToolDef(
            name="write",
            description="在沙箱目录内新建文本文件（相对路径）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            permission="sandbox.write",
            timeout_s=10.0,
            handler=_write_handler,
            display_name="写入文件",
            risk_level="modify",
        )
    )
    registry.register(
        ToolDef(
            name="edit",
            description="在沙箱目录内编辑文本文件（原子替换）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
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
            display_name="编辑文件",
            risk_level="modify",
        )
    )
    registry.register(
        ToolDef(
            name="web_search",
            description="内部搜索引擎检索（平台自实现适配器，不走外部 MCP）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "limit": {"type": "integer", "description": "返回结果数，默认 5，最大 10", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
            permission="web.search",
            timeout_s=20.0,
            handler=_web_search_handler,
            display_name="网页检索",
            risk_level="network",
        )
    )
    registry.register(
        ToolDef(
            name="web_fetch",
            description="内部网页抓取（平台自实现适配器 + 脱敏，不走外部 MCP）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2048},
                    "format": {"type": "string", "enum": ["markdown", "text"], "description": "优先返回 Markdown，默认 markdown"},
                },
                "required": ["url"],
            },
            permission="web.fetch",
            timeout_s=20.0,
            handler=_web_fetch_handler,
            display_name="网页抓取",
            risk_level="network",
        )
    )
    registry.register(
        ToolDef(
            name="bash",
            description="在 bwrap 沙箱内执行 shell 命令（相对路径、无网络、受资源限制）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
            permission="sandbox.bash",
            timeout_s=15.0,
            handler=_bash_handler,
            display_name="沙箱命令",
            risk_level="code",
        )
    )
    registry.register(
        ToolDef(
            name="task",
            description="维护本回合的执行清单：把复杂需求拆解为有限步骤并标注状态。该工具不创建评测任务、不写数据库、不绕过确认卡或 Worker。",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "goal": {"type": "string", "minLength": 1, "maxLength": 500, "description": "本轮目标"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["goal", "steps"],
            },
            permission="task.plan",
            timeout_s=2.0,
            handler=_task_handler,
            display_name="拆解任务",
            risk_level="read",
        )
    )
    return registry


def _read_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> object:
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


def _write_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> object:
    """write 工具 handler：受控目录内写入相对路径（防目录穿越）。"""
    from .dispatch import write_file_safe

    return write_file_safe(
        str(arguments.get("path", "")),
        str(arguments.get("content", "")),
        sandbox_dir or "",
    )


def _edit_handler(arguments: Mapping[str, object], sandbox_dir: str | None = None) -> object:
    """edit 工具 handler：受控目录内原子替换（防目录穿越）。"""
    from .dispatch import edit_file_safe

    return edit_file_safe(
        str(arguments.get("path", "")),
        str(arguments.get("old", "")),
        str(arguments.get("new", "")),
        sandbox_dir or "",
    )


def _web_search_handler(arguments: Mapping[str, object], _sandbox_dir: str | None = None) -> object:
    """web_search 原生 handler：服务端 Firecrawl REST 适配器。"""
    from .dispatch import web_search

    return web_search(
        str(arguments.get("query", "")),
        limit=arguments.get("limit"),
        timeout_s=20.0,
    )


def _web_fetch_handler(arguments: Mapping[str, object], _sandbox_dir: str | None = None) -> object:
    """web_fetch 原生 handler：带 SSRF 防护的服务端抓取器。"""
    from .dispatch import web_fetch

    return web_fetch(
        str(arguments.get("url", "")),
        format=str(arguments.get("format") or "markdown"),
        timeout_s=20.0,
    )


def _task_handler(arguments: Mapping[str, object], _sandbox_dir: str | None = None) -> object:
    """task 原生 handler：仅生成本回合任务清单，不触发平台长任务副作用。"""
    from .dispatch import build_task_plan

    return build_task_plan(arguments)


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
