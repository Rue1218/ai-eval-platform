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
from dataclasses import dataclass, field
from typing import Literal

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolDescriptor

from .policy import DEFAULT_RECOVERY_POLICY, ToolPermissionPolicy, ToolRecoveryPolicy

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
    # 输出、权限与恢复策略与输入 Schema 同属工具契约，禁止在前端或 handler
    # 分别维护第二份规则。默认值仅兼容历史测试/内部扩展，新工具必须显式声明。
    output_schema: Mapping[str, object] = field(default_factory=dict)  # 浏览器安全投影 Schema
    permission_policy: ToolPermissionPolicy = ToolPermissionPolicy()
    recovery_policy: ToolRecoveryPolicy = DEFAULT_RECOVERY_POLICY
    # 为既有内部扩展保持 MCP 默认值；基础工具在 build_default_registry 中显式
    # 标为 native，避免因默认值变化误入 MCP。
    transport: Literal["native", "mcp"] = "mcp"  # 执行通道
    server_id: str = ""  # 如 "platform.files"（空则目录按名称推断归属）
    display_name: str = ""  # 如 "读取文件"
    risk_level: Literal["read", "modify", "network", "code", "long"] = "read"
    execution_mode: Literal["short", "long"] = "short"
    requires_confirmation: bool = False
    supports_streaming: bool = False
    contextual: bool = False  # True 时 handler 接收 (arguments, sandbox_dir, ToolExecutionContext)
    # 仅执行层调度使用，不投影到模型 tools、MCP 目录或浏览器。
    concurrency_class: Literal["read_only", "path_scoped", "exclusive", "session_exclusive"] = (
        "exclusive"
    )
    requires_prior_result: bool = False

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
            output_schema=dict(self.output_schema or {}),
            permission=self.permission,
            permission_policy=self.permission_policy.to_payload(),
            recovery_policy={
                "retryable_codes": sorted(self.recovery_policy.retryable_codes),
                "suggested_action": self.recovery_policy.suggested_action,
                "default_hint": self.recovery_policy.default_hint,
                "max_auto_repairs": self.recovery_policy.max_auto_repairs,
            },
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
        output_schema_error = validate_tool_schema(def_.output_schema)
        if output_schema_error:
            raise AppError(ErrorCode.VALIDATION, f"工具输出 Schema 无效：{output_schema_error}")
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
                "output_schema": dict(definition.output_schema or {}),
                "permission": definition.permission,
                "permission_policy": definition.permission_policy.to_payload(),
                "recovery_policy": {
                    "retryable_codes": sorted(definition.recovery_policy.retryable_codes),
                    "suggested_action": definition.recovery_policy.suggested_action,
                    "default_hint": definition.recovery_policy.default_hint,
                    "max_auto_repairs": definition.recovery_policy.max_auto_repairs,
                },
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
            "output_schema": dict(definition.output_schema or {}),
            "permission": definition.permission,
            "permission_policy": definition.permission_policy.to_payload(),
            "recovery_policy": {
                "retryable_codes": sorted(definition.recovery_policy.retryable_codes),
                "suggested_action": definition.recovery_policy.suggested_action,
                "default_hint": definition.recovery_policy.default_hint,
                "max_auto_repairs": definition.recovery_policy.max_auto_repairs,
            },
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
    """注册原生基础工具与 ``platform.tasks`` MCP 评测任务桥。

    ``read/write/edit/web_search/web_fetch/bash/task`` 均经原生 ToolCall 直连；
    bash 由独立 Runner 的 bwrap 沙箱执行并 fail-closed。``task`` 只维护本回合
    的拆解清单。``task.create/status/cancel`` 则是显式 ``transport=mcp`` 的
    评测任务扩展：只入 PG 队列、查询或取消，不等待 Worker 终态。
    """
    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="read",
            description=(
                "按行读取沙箱目录内的文本文件（相对路径）。"
                "适用：查看附件、工作区文件、确认 edit 前的原文。"
                "不适用：创建文件（用 write）、改文件（用 edit）、执行命令（用 bash）。"
                "前置：path 必须是沙箱相对路径。offset/limit 均为 0-based 行，"
                "单次最多 2000 行和 600000 字符；未读完时把返回的 "
                "next_offset 填到下一次 offset，不要用相同 offset 重复读取。大文件只解码当前窗口。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "相对路径"},
                    "offset": {"type": "integer", "description": "起始行号，0-based，默认 0", "minimum": 0},
                    "next_offset": {
                        "type": "integer",
                        "description": "与 offset 同义；可把上次返回的 next_offset 填到这里",
                        "minimum": 0,
                    },
                    "limit": {"type": "integer", "description": "最多读取行数，默认/上限 2000", "minimum": 1, "maximum": 2000},
                },
                "required": ["path"],
            },
            permission="sandbox.read",
            timeout_s=20.0,
            handler=_read_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "read": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "total_lines": {"type": "integer"},
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                            "next_offset": {"type": ["integer", "null"]},
                            "preview": {"type": "string"},
                        },
                    },
                },
            },
            permission_policy=ToolPermissionPolicy(workspace="read"),
            recovery_policy=ToolRecoveryPolicy(
                retryable_codes=frozenset({"TIMEOUT"}),
                suggested_action="read_next_page",
                default_hint="请检查相对路径，或使用 next_offset 读取下一页。",
            ),
            transport="native",
            display_name="读取文件",
            risk_level="read",
            supports_streaming=True,
            contextual=True,
            concurrency_class="path_scoped",
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
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "write": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "bytes_written": {"type": "integer"},
                            "lines_written": {"type": "integer"},
                            "preview": {"type": "string"},
                        },
                    },
                },
            },
            permission_policy=ToolPermissionPolicy(workspace="write"),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="choose_new_path",
                default_hint="文件不会被覆盖；请改用新路径，或先 read 后使用 edit。",
                max_auto_repairs=0,
            ),
            transport="native",
            display_name="写入文件",
            risk_level="modify",
            supports_streaming=True,
            contextual=True,
            concurrency_class="path_scoped",
        )
    )
    registry.register(
        ToolDef(
            name="edit",
            description=(
                "在沙箱目录内对已有文本文件做精确字符串替换。"
                "适用：修改已存在文件的一小段原文。"
                "不适用：新建文件（用 write）、查看内容（用 read）。"
                "前置：必须先 read 确认 old 与文件中的文本完全一致（含空白）；"
                "old 在文件中必须能唯一匹配，否则会失败并返回邻近行修复建议。"
            ),
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
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "edit": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "replacements": {"type": "integer"},
                            "old_length": {"type": "integer"},
                            "new_length": {"type": "integer"},
                        },
                    },
                },
            },
            permission_policy=ToolPermissionPolicy(workspace="write"),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="read_then_edit",
                default_hint="请先 read 确认 old 与文件原文完全一致后再编辑。",
                max_auto_repairs=1,
            ),
            transport="native",
            display_name="编辑文件",
            risk_level="modify",
            contextual=True,
            concurrency_class="path_scoped",
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
            output_schema={
                "type": "object",
                "properties": {"summary": {"type": "string"}, "search": {"type": "object"}},
            },
            permission_policy=ToolPermissionPolicy(network="public_only"),
            recovery_policy=ToolRecoveryPolicy(
                retryable_codes=frozenset({"TIMEOUT", "UPSTREAM"}),
                suggested_action="retry_query",
                default_hint="请稍后重试，或缩短并调整搜索关键词。",
            ),
            transport="native",
            display_name="网页检索",
            risk_level="network",
            concurrency_class="read_only",
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
            output_schema={
                "type": "object",
                "properties": {"summary": {"type": "string"}, "web": {"type": "object"}},
            },
            permission_policy=ToolPermissionPolicy(network="public_only"),
            recovery_policy=ToolRecoveryPolicy(
                retryable_codes=frozenset({"TIMEOUT", "UPSTREAM"}),
                suggested_action="retry_public_url",
                default_hint="请确认 URL 可公开访问；内网与回环地址不会重试。",
            ),
            transport="native",
            display_name="网页抓取",
            risk_level="network",
            supports_streaming=True,
            contextual=True,
            concurrency_class="read_only",
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
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "bash": {
                        "type": "object",
                        "properties": {
                            "exit_code": {"type": "integer"},
                            "preview": {"type": "string"},
                            "preview_truncated": {"type": "boolean"},
                        },
                    },
                },
            },
            permission_policy=ToolPermissionPolicy(workspace="write"),
            recovery_policy=ToolRecoveryPolicy(
                retryable_codes=frozenset({"TIMEOUT"}),
                suggested_action="reduce_command_scope",
                default_hint="请缩小命令处理范围；沙箱或安全策略拒绝时不得绕过重试。",
                max_auto_repairs=0,
            ),
            transport="native",
            display_name="沙箱命令",
            risk_level="code",
            supports_streaming=True,
            contextual=True,
            concurrency_class="exclusive",
        )
    )
    registry.register(
        ToolDef(
            name="task",
            description=(
                "维护本回合的执行清单：把复杂需求拆成有限步骤并标注状态。"
                "适用：多步评测/用例/压测前先列出 3–7 步计划。"
                "不适用：真正创建评测任务（用确认卡或 platform.tasks.task.create）、"
                "查询/取消已入队任务（用 task.status / task.cancel）。"
                "前置：goal 与 steps 必填；不写数据库、不绕过确认卡或 Worker。"
            ),
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
            output_schema={
                "type": "object",
                "properties": {"summary": {"type": "string"}, "task": {"type": "object"}},
            },
            permission_policy=ToolPermissionPolicy(),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="adjust_plan",
                default_hint="请补充目标或将步骤缩减为可执行的有限清单。",
            ),
            transport="native",
            display_name="拆解任务",
            risk_level="read",
            concurrency_class="read_only",
        )
    )
    # ── platform.tasks 长任务 MCP：只入队/查询/取消，不等待终态 ──
    registry.register(
        ToolDef(
            name="task.create",
            description="创建评测任务并入队（benchmark/testcase/rag/stress），由 Worker 异步执行；返回 queued + task_id，不等待终态。",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["benchmark", "testcase", "rag", "stress"],
                        "description": "任务类型",
                    },
                    "dataset_id": {"type": "string", "description": "数据集 ID（非 stress 必填）"},
                    "profile_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "模型协议档 ID 列表",
                    },
                    "kb_id": {"type": "string", "description": "知识库 ID（rag）"},
                    "gold_qa_id": {"type": "string", "description": "黄金 QA ID（rag）"},
                    "rag_mode": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["naive", "local", "global", "hybrid"],
                        },
                    },
                    "with_stress": {"type": "boolean"},
                    "parent_task_id": {"type": "string", "description": "压测父任务 ID（kind=stress 必填）"},
                },
                "required": ["kind"],
            },
            permission="task.create",
            timeout_s=10.0,
            handler=_task_create_handler,
            transport="mcp",
            server_id="platform.tasks",
            display_name="创建评测任务",
            risk_level="modify",
            contextual=True,
            concurrency_class="session_exclusive",
        )
    )
    registry.register(
        ToolDef(
            name="task.status",
            description="查询评测任务当前状态（kind/status/progress/report_id），不等待完成",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
            permission="task.status",
            timeout_s=10.0,
            handler=_task_status_handler,
            transport="mcp",
            server_id="platform.tasks",
            display_name="查询任务状态",
            risk_level="read",
            contextual=True,
            concurrency_class="read_only",
        )
    )
    registry.register(
        ToolDef(
            name="task.cancel",
            description="取消非终态评测任务（终态任务幂等返回现状）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
            permission="task.cancel",
            timeout_s=10.0,
            handler=_task_cancel_handler,
            transport="mcp",
            server_id="platform.tasks",
            display_name="取消评测任务",
            risk_level="modify",
            contextual=True,
            concurrency_class="session_exclusive",
        )
    )
    return registry


def _read_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """read 工具 handler：受控目录内读取相对路径（防目录穿越）。

    ``sandbox_dir`` 由平台经 dispatch 注入，**禁止模型传参**（M5-D7 红线）；
    ``offset``/``limit`` 支持长文本分段读取。
    """
    from .dispatch import read_file_safe, resolve_read_offset

    return read_file_safe(
        str(arguments.get("path", "")),
        sandbox_dir or "",
        offset=resolve_read_offset(arguments),
        limit=arguments.get("limit"),
        on_output=getattr(context, "report_output", None),
    )


def _write_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """write 工具 handler：受控目录内写入相对路径（防目录穿越）。"""
    from .dispatch import write_file_safe

    result = write_file_safe(
        str(arguments.get("path", "")),
        str(arguments.get("content", "")),
        sandbox_dir or "",
    )
    reporter = getattr(context, "report_output", None)
    if callable(reporter) and result.preview:
        reporter("document", result.preview, 1)
    return result


def _edit_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """edit 工具 handler：受控目录内原子替换（防目录穿越）。"""
    from .dispatch import edit_file_safe

    return edit_file_safe(
        str(arguments.get("path", "")),
        str(arguments.get("old", "")),
        str(arguments.get("new", "")),
        sandbox_dir or "",
    )


def _web_search_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """web_search 原生 handler：服务端 Firecrawl REST 适配器。"""
    from .dispatch import web_search

    return web_search(
        str(arguments.get("query", "")),
        limit=arguments.get("limit"),
        timeout_s=20.0,
    )


def _web_fetch_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """web_fetch 原生 handler：带 SSRF 防护的服务端抓取器。"""
    from .dispatch import web_fetch

    return web_fetch(
        str(arguments.get("url", "")),
        format=str(arguments.get("format") or "markdown"),
        timeout_s=20.0,
    )


def _task_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """task 原生 handler：仅生成本回合任务清单，不触发平台长任务副作用。"""
    from .dispatch import build_task_plan

    return build_task_plan(arguments)


def _bash_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """bash 工具 handler：bwrap 沙箱内执行（阶段 3 开放通用 bash）。

    资源限制读 Settings（内存/进程数/CPU），``sandbox_dir`` 由平台注入，
    禁止模型传参（M5-D7 红线）；引擎为 "off" 或 bwrap 不可用时 fail-closed
    （VALIDATION），禁止降级为裸 subprocess。
    """
    from app.config import settings
    from app.harness.execution.dispatch import BashResult, run_bash
    from app.harness.execution.sandbox import SandboxLimits

    if settings.sandbox_engine != "bwrap":
        raise AppError(ErrorCode.VALIDATION, "沙箱引擎未启用")
    limits = SandboxLimits(
        memory_kb=settings.sandbox_memory_mb * 1024,
        nproc=settings.sandbox_nproc,
        cpu_s=settings.sandbox_cpu_s,
    )
    output = run_bash(
        str(arguments.get("command", "")),
        sandbox_dir=sandbox_dir or "",
        timeout_s=15.0,
        limits=limits,
        on_output=getattr(context, "report_output", None),
    )
    return BashResult(output)


def _task_create_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task.create 工具 handler：长任务直接入队（platform.tasks MCP，P4-1）。

    会话/用户来自 ``ToolExecutionContext``（平台注入，模型不可传）；经
    ``task_tools.create_task_safe`` 校验并 ``enqueue_long_task``，返回
    ``{status: queued, task_id, kind}``，不等待 Worker 终态。
    """
    from .task_tools import create_task_safe

    return create_task_safe(arguments, context)


def _task_status_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task.status 工具 handler：只读查询任务状态（platform.tasks MCP，P4-1）。"""
    from .task_tools import status_task_safe

    return status_task_safe(arguments, context)


def _task_cancel_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task.cancel 工具 handler：行锁取消非终态任务（platform.tasks MCP，P4-1）。"""
    from .task_tools import cancel_task_safe

    return cancel_task_safe(arguments, context)
