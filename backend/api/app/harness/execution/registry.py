"""Harness 执行层：工具注册表（M5 阶段 2，EX-1/EX-5）。

工具元数据、白名单与执行分派的**唯一来源**：新增工具必须登记并走统一执行
入口；未注册工具调用一律拒绝（VALIDATION），禁止假成功。``ToolDef.handler``
为运行时执行函数（不入 GraphState，仅注册表持有）。基础文件、网络、沙箱与
任务拆解工具固定为 ``transport=native``；只有评测/RAG 等后续扩展工具才允许
显式标记为 ``transport=mcp`` 并投影到内部 MCP 目录。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolDescriptor

from .policy import DEFAULT_RECOVERY_POLICY, ToolPermissionPolicy, ToolRecoveryPolicy
from .registry_schema import (  # noqa: F401  （对外兼容导出；schema 校验实现见 registry_schema）
    required_parameter_names,
    validate_tool_arguments,
    validate_tool_output,
    validate_tool_schema,
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
    # 分别维护第二份规则。``output_schema`` 为 ``None`` 表示未声明（注册期拒绝）；
    # 显式传 ``{}`` 表示「无结构化展示投影」（合法，运行期跳过比对）。
    output_schema: Mapping[str, object] | None = None  # 浏览器安全投影 Schema
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
            output_schema=dict(self.output_schema or {}),  # None 与 {} 均投影为 {}
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
        # output_schema 是浏览器展示投影的契约，必须显式声明且自身合法。
        # None（未声明）拒绝；显式 {} 表示无结构化投影，合法但运行期不做比对。
        if def_.output_schema is None:
            raise AppError(ErrorCode.VALIDATION, f"工具必须声明 output_schema：{def_.name}")
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


def build_default_registry() -> ToolRegistry:
    """注册原生基础工具与 ``platform.tasks`` MCP 评测任务桥。

    ``read/read_image/glob/grep/write/edit/web_search/web_fetch/bash/task`` 均经原生 ToolCall 直连；
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
                "前置：path 必须是沙箱相对路径。offset/limit 均为 0-based 行。"
                "推荐用法：除非只需要局部行段，否则省略 limit 一次读完——单次最多 "
                "2000 行和 600000 字符，1000 行量级的文件一次即可读完，禁止人为拆成"
                "多个小窗口连续多次读取。未读完时把返回的 "
                "next_offset 填到下一次 offset，不要用相同 offset 重复读取。大文件只解码当前窗口。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "file_path": {"type": "string", "description": "会话工作区相对路径"},
                    "offset": {"type": "integer", "description": "起始行号，0-based，默认 0", "minimum": 0},
                    "limit": {
                        "type": "integer",
                        "description": "最多读取行数；建议省略以一次读完，默认/上限 2000",
                        "minimum": 1,
                        "maximum": 2000,
                    },
                },
                "required": ["file_path"],
            },
            permission="sandbox.read",
            timeout_s=20.0,
            handler=_read_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "status": {"type": "string"},
                    "content": {"type": "string"},
                    "metadata": {"type": "object"},
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
            name="read_image",
            description=(
                "读取会话工作区内的 PNG、JPEG、GIF 或 WebP 图片。"
                "适用：用户要求分析工作区图片，或先用 glob 定位图片后查看。"
                "前置：file_path 必须是沙箱相对路径；单张图片不得超过 4MB。"
                "图片只在当前模型回合以图文块传递，持久日志和 ToolCard 仅保存元数据摘要。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"file_path": {"type": "string", "description": "会话工作区相对图片路径"}},
                "required": ["file_path"],
            },
            permission="sandbox.read",
            timeout_s=20.0,
            handler=_read_image_handler,
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "status": {"type": "string"},
                    "read_image": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "path": {"type": "string"}, "media_type": {"type": "string"},
                            "size_bytes": {"type": "integer"}, "width": {"type": ["integer", "null"]},
                            "height": {"type": ["integer", "null"]},
                        },
                        "required": ["path", "media_type", "size_bytes", "width", "height"],
                    },
                },
                "required": ["summary", "status", "read_image"],
            },
            permission_policy=ToolPermissionPolicy(workspace="read"),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="choose_supported_image",
                default_hint="请确认路径指向不超过 4MB 的 PNG、JPEG、GIF 或 WebP 图片。",
            ),
            transport="native",
            display_name="读取图片",
            risk_level="read",
            contextual=True,
            concurrency_class="path_scoped",
        )
    )
    registry.register(
        ToolDef(
            name="glob",
            description=(
                "按 glob 模式查找会话工作区内的普通文件。"
                "pattern 不含斜杠时匹配任意目录层级的文件名；可选 path 限定起始目录。"
                "结果只返回相对路径，自动排除版本库、依赖缓存和符号链接。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 500, "description": "文件 glob 模式"},
                    "path": {"type": "string", "description": "可选的工作区相对起始目录"},
                },
                "required": ["pattern"],
            },
            permission="sandbox.read",
            timeout_s=20.0,
            handler=_glob_handler,
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"}, "status": {"type": "string"}, "content": {"type": "string"},
                    "glob": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "query": {"type": "string"}, "count": {"type": "integer"},
                            "truncated": {"type": "boolean"}, "preview": {"type": "string"},
                        },
                        "required": ["query", "count", "truncated", "preview"],
                    },
                },
                "required": ["summary", "status", "content", "glob"],
            },
            permission_policy=ToolPermissionPolicy(workspace="read"),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="narrow_glob",
                default_hint="请缩小 path 或使用更具体的 pattern。",
            ),
            transport="native",
            display_name="查找文件",
            risk_level="read",
            contextual=True,
            concurrency_class="path_scoped",
        )
    )
    registry.register(
        ToolDef(
            name="grep",
            description=(
                "在会话工作区文本文件中按 Python 正则搜索内容，返回 path:line:text。"
                "可选 path 限定搜索目录，include 用 glob 过滤文件；自动跳过二进制文件、"
                "版本库、依赖缓存和符号链接。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 500, "description": "Python 正则表达式"},
                    "path": {"type": "string", "description": "可选的工作区相对起始目录"},
                    "include": {"type": "string", "maxLength": 500, "description": "可选的文件 glob 过滤模式"},
                },
                "required": ["pattern"],
            },
            permission="sandbox.read",
            timeout_s=20.0,
            handler=_grep_handler,
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"}, "status": {"type": "string"}, "content": {"type": "string"},
                    "grep": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "query": {"type": "string"}, "count": {"type": "integer"},
                            "truncated": {"type": "boolean"}, "preview": {"type": "string"},
                        },
                        "required": ["query", "count", "truncated", "preview"],
                    },
                },
                "required": ["summary", "status", "content", "grep"],
            },
            permission_policy=ToolPermissionPolicy(workspace="read"),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="narrow_grep",
                default_hint="请缩小 path、include 或正则表达式的匹配范围。",
            ),
            transport="native",
            display_name="搜索文件内容",
            risk_level="read",
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
                    "file_path": {"type": "string", "description": "目标文件相对路径，不存在则新建"},
                    "content": {"type": "string", "description": "完整文本内容"},
                    "description": {"type": "string", "description": "简短操作描述"},
                    "reviewComment": {"type": "string", "description": "写操作动机，仅供审查展示"},
                },
                "required": ["file_path", "content"],
            },
            permission="sandbox.write",
            timeout_s=10.0,
            handler=_write_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "status": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
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
                    "file_path": {"type": "string", "description": "目标文件相对路径"},
                    "old_string": {"type": "string", "description": "需唯一精确匹配的原文"},
                    "new_string": {"type": "string", "description": "替换后的新文本，空串表示删除"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "为 true 时替换全部匹配，否则多处匹配会失败",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            permission="sandbox.write",
            timeout_s=10.0,
            handler=_edit_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "status": {"type": "string"},
                    "modified_lines": {"type": "integer"},
                    "diff": {"type": "string"},
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
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果数，默认 5，平台上限 10",
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "topic": {"type": "string", "description": "主题，仅展示"},
                    "time_range": {"type": "string", "description": "时间筛选，仅展示"},
                    "include_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "限定来源域名，本轮不改变检索实现",
                    },
                    "exclude_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "排除域名，本轮不改变检索实现",
                    },
                    "engine": {"type": "string", "description": "仅 auto/native"},
                    "search_context_size": {"type": "string", "description": "上下文长度提示，仅展示"},
                },
                "required": ["query"],
            },
            permission="web.search",
            timeout_s=20.0,
            handler=_web_search_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "results": {"type": "array"},
                    "search": {"type": "object"},
                },
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
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "允许访问的域名白名单",
                    },
                    "blocked_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "禁止访问的域名黑名单",
                    },
                    "max_content_tokens": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "映射到现有字符预算，不放宽 60000",
                    },
                    "engine": {"type": "string", "description": "仅 auto/native"},
                },
                "required": ["url"],
            },
            permission="web.fetch",
            timeout_s=20.0,
            handler=_web_fetch_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "content": {"type": "string"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "web": {"type": "object"},
                },
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
            description="在受控沙箱容器内执行 shell 命令（工作区可写、受资源限制；网络按权限档位）",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command": {"type": "string", "description": "完整 shell 命令，仅在沙箱容器内运行"},
                    "description": {"type": "string", "description": "命令简短描述"},
                    "timeout": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "超时毫秒，封顶现有沙箱墙钟 15000",
                    },
                    "run_in_background": {"type": "boolean", "description": "必须为 false；true 会被拒绝"},
                    "dangerouslyDisableSandbox": {
                        "type": "boolean",
                        "description": "必须为 false；true 会被拒绝",
                    },
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
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                    "exit_code": {"type": "integer"},
                    "duration_ms": {"type": "integer"},
                    "is_background": {"type": "boolean"},
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
                "维护当前会话的执行清单：仅在复杂、多步骤、需要跟踪进度的工作开始前调用。"
                "适用：包含多个相互依赖步骤、需要调用多种工具、排查不确定问题，或需要向用户展示推进状态的任务。"
                "不适用：简单单步问答、一次读取或一次修改；这些任务直接执行，不要创建清单。"
                "每次必须提交完整 steps 列表，新列表整体替换上一份；开始执行后及时把对应步骤更新为 in_progress，"
                "完成后立即更新为 completed。"
                "不适用：真正创建评测任务（用确认卡或 platform.tasks.task.create）、"
                "查询/取消已入队任务（用 task.status / task.cancel）、启动子代理。"
                "前置：description 概括本轮目标，steps 是有限的具体步骤；不写 PG 任务表、不绕过确认卡或 Worker。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80,
                        "description": "任务简短概括",
                    },
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                        "description": "兼容旧调用的完整目标；新调用以 description 为准",
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "description": "当前完整步骤清单；每次调用整体替换上一份清单",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            },
                            "required": ["title", "status"],
                        },
                    },
                    "subagent_type": {"type": "string", "description": "仅展示，不启子代理"},
                    "model": {"type": "string", "description": "仅展示，不切换模型"},
                    "resume": {"type": "string", "description": "仅展示，不恢复子会话"},
                    "run_in_background": {"type": "boolean", "description": "必须为 false"},
                    "tools": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "仅展示"},
                    "max_turns": {"type": "integer", "minimum": 1, "description": "仅展示"},
                },
                "required": ["description", "steps"],
            },
            permission="task.plan",
            timeout_s=2.0,
            handler=_task_handler,
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "status": {"type": "string", "enum": ["success"]},
                    "result": {"type": "string"},
                    "task": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "goal": {"type": "string"},
                            "description": {"type": "string"},
                            "prompt": {"type": "string"},
                            "steps": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "title": {"type": "string"},
                                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                    },
                                    "required": ["title", "status"],
                                },
                            },
                        },
                        "required": ["goal", "description", "prompt", "steps"],
                    },
                },
                "required": ["summary", "status", "result", "task"],
            },
            permission_policy=ToolPermissionPolicy(),
            recovery_policy=ToolRecoveryPolicy(
                suggested_action="adjust_plan",
                default_hint="请补充目标或将步骤缩减为可执行的有限清单。",
            ),
            transport="native",
            display_name="拆解任务",
            risk_level="read",
            contextual=True,
            concurrency_class="read_only",
        )
    )
    registry.register(
        ToolDef(
            name="TaskCreate",
            description=(
                "在当前会话看板创建一项拆解任务，返回 task.id。"
                "不创建评测入队任务（那是 task.create），不启子代理。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subject": {"type": "string", "minLength": 1, "maxLength": 120},
                    "description": {"type": "string", "maxLength": 2000},
                    "activeForm": {"type": "string", "maxLength": 80},
                    "metadata": {"type": "object"},
                },
                "required": ["subject"],
            },
            permission="task.plan",
            timeout_s=2.0,
            handler=_session_task_create_handler,
            output_schema={"type": "object", "properties": {"task": {"type": "object"}, "status": {"type": "string"}}},
            permission_policy=ToolPermissionPolicy(),
            transport="native",
            display_name="TaskCreate",
            risk_level="read",
            contextual=True,
            concurrency_class="exclusive",
        )
    )
    registry.register(
        ToolDef(
            name="TaskGet",
            description="按 taskId 读取会话看板中的一项；找不到返回 null。不是评测任务详情。",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"taskId": {"type": "string", "minLength": 1}},
                "required": ["taskId"],
            },
            permission="task.plan",
            timeout_s=2.0,
            handler=_session_task_get_handler,
            output_schema={"type": "object"},
            permission_policy=ToolPermissionPolicy(),
            transport="native",
            display_name="TaskGet",
            risk_level="read",
            contextual=True,
            concurrency_class="read_only",
        )
    )
    registry.register(
        ToolDef(
            name="TaskUpdate",
            description=(
                "更新会话看板任务的状态或字段。status=deleted 表示删除。"
                "in_progress 且未指定 owner 时写入当前用户，避免重复认领。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "taskId": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]},
                    "subject": {"type": "string", "maxLength": 120},
                    "description": {"type": "string", "maxLength": 2000},
                    "activeForm": {"type": "string", "maxLength": 80},
                    "owner": {"type": "string", "maxLength": 64},
                    "addBlocks": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    "addBlockedBy": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    "metadata": {"type": "object"},
                },
                "required": ["taskId", "status"],
            },
            permission="task.plan",
            timeout_s=2.0,
            handler=_session_task_update_handler,
            output_schema={"type": "object"},
            permission_policy=ToolPermissionPolicy(),
            transport="native",
            display_name="TaskUpdate",
            risk_level="read",
            contextual=True,
            concurrency_class="exclusive",
        )
    )
    registry.register(
        ToolDef(
            name="TaskList",
            description="返回当前会话看板快照，用于读取整体拆解进度。无入参。",
            parameters_schema={"type": "object", "additionalProperties": False, "properties": {}},
            permission="task.plan",
            timeout_s=2.0,
            handler=_session_task_list_handler,
            output_schema={"type": "object"},
            permission_policy=ToolPermissionPolicy(),
            transport="native",
            display_name="TaskList",
            risk_level="read",
            contextual=True,
            concurrency_class="read_only",
        )
    )
    registry.register(
        ToolDef(
            name="ask_user_question",
            description=(
                "向用户提出一个或多个澄清问题，暂停图直到用户回复。"
                "复用 clarify / clarify_reply，不入队评测任务。"
            ),
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "minLength": 1},
                                "question": {"type": "string", "minLength": 1},
                                "header": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "maxItems": 10,
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "label": {"type": "string"},
                                            "description": {"type": "string"},
                                        },
                                        "required": ["label"],
                                    },
                                },
                                "multi_select": {"type": "boolean"},
                                "required": {"type": "boolean"},
                                "type": {"type": "string", "enum": ["radio", "checkbox", "text"]},
                            },
                            "required": ["id", "question"],
                        },
                    }
                },
                "required": ["questions"],
            },
            permission="task.plan",
            timeout_s=2.0,
            handler=_ask_user_question_handler,
            output_schema={"type": "object", "properties": {"answers": {"type": "array"}}},
            permission_policy=ToolPermissionPolicy(),
            transport="native",
            display_name="ask_user_question",
            risk_level="read",
            contextual=True,
            concurrency_class="exclusive",
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
                        "maxItems": 10,
                        "description": "模型协议档 ID 列表",
                    },
                    "kb_id": {"type": "string", "description": "知识库 ID（rag）"},
                    "gold_qa_id": {"type": "string", "description": "黄金 QA ID（rag）"},
                    "rag_mode": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {
                            "type": "string",
                            "enum": ["naive", "local", "global", "hybrid"],
                        },
                    },
                    "run": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "sample_size": {"type": "integer", "minimum": 1, "maximum": 1000},
                            "concurrency": {"type": "integer", "minimum": 1, "maximum": 100},
                            "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600},
                            "retry": {"type": "integer", "minimum": 0, "maximum": 5},
                            "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                            "max_tokens": {"type": "integer", "minimum": 1, "maximum": 32768},
                            "system_prompt": {"type": "string", "maxLength": 20000},
                            "k": {"type": "integer", "minimum": 1, "maximum": 20},
                            "use_judge": {"type": "boolean"},
                            "judge_profile_id": {"type": "string"},
                        },
                        "description": "benchmark/RAG 的可复现运行配置",
                    },
                    "with_stress": {"type": "boolean"},
                    "stress": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "env": {"type": "string", "enum": ["dev", "test", "staging", "prod"]},
                            "qps": {"type": "integer", "minimum": 1, "maximum": 500},
                            "duration_s": {"type": "integer", "minimum": 1, "maximum": 1800},
                            "sla_p99_ms": {"type": "integer", "minimum": 1},
                        },
                        "required": ["env", "qps", "duration_s"],
                        "description": "质量任务成功后派生压测的配置",
                    },
                    "case_source": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "file_id": {"type": "string"},
                            "text": {"type": "string", "maxLength": 1000000},
                        },
                        "description": "用例生成来源；file_id/text 二选一",
                    },
                    "parent_task_id": {"type": "string", "description": "压测父任务 ID（kind=stress 必填）"},
                },
                "required": ["kind"],
            },
            permission="task.create",
            timeout_s=10.0,
            handler=_task_create_handler,
            output_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["queued"]},
                    "task_id": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["status", "task_id", "kind"],
            },
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
            output_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "status": {"type": "string"},
                    "progress": {"type": "object"},
                    "report_id": {"type": ["string", "null"]},
                },
                "required": ["task_id", "kind", "status"],
            },
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
            output_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["task_id", "status", "kind"],
            },
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
        str(arguments.get("file_path") or arguments.get("path") or ""),
        sandbox_dir or "",
        offset=resolve_read_offset(arguments),
        limit=arguments.get("limit"),
        on_output=getattr(context, "report_output", None),
    )


def _read_image_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """read_image 工具 handler：只从受控工作区读取小型常见图片。"""
    from .dispatch import read_image_safe

    return read_image_safe(str(arguments.get("file_path") or ""), sandbox_dir or "")


def _glob_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """glob 工具 handler：在受控工作区枚举匹配文件。"""
    from .dispatch import glob_files_safe

    path = arguments.get("path")
    return glob_files_safe(
        str(arguments.get("pattern") or ""), sandbox_dir or "",
        str(path) if isinstance(path, str) else None,
    )


def _grep_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """grep 工具 handler：在受控工作区文本文件中执行受限正则搜索。"""
    from .dispatch import grep_files_safe

    path, include = arguments.get("path"), arguments.get("include")
    return grep_files_safe(
        str(arguments.get("pattern") or ""), sandbox_dir or "",
        path=str(path) if isinstance(path, str) else None,
        include=str(include) if isinstance(include, str) else None,
    )


def _write_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """write 工具 handler：受控目录内写入相对路径（防目录穿越）。"""
    from .dispatch import write_file_safe

    progress = getattr(context, "report_progress", None)
    if callable(progress):
        progress("writing", "正在以原子方式写入文件")
    result = write_file_safe(
        str(arguments.get("file_path") or arguments.get("path") or ""),
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
        str(arguments.get("file_path") or arguments.get("path") or ""),
        str(arguments.get("old_string") or arguments.get("old") or ""),
        str(arguments.get("new_string") if arguments.get("new_string") is not None else arguments.get("new") or ""),
        sandbox_dir or "",
        replace_all=arguments.get("replace_all") is True,
    )


def _web_search_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """web_search 原生 handler：服务端 Firecrawl REST 适配器。"""
    from .dispatch import web_search

    progress = getattr(_context, "report_progress", None)
    if callable(progress):
        progress("searching", "正在请求受控网络检索服务")
    result = web_search(
        str(arguments.get("query", "")),
        limit=arguments.get("max_results", arguments.get("limit")),
        timeout_s=20.0,
    )
    if callable(progress):
        progress("formatting", "正在整理安全检索结果")
    return result


def _web_fetch_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """web_fetch 原生 handler：带 SSRF 防护的服务端抓取器。"""
    from .dispatch import apply_fetch_content_budget, assert_fetch_domains, web_fetch

    url = str(arguments.get("url", ""))
    assert_fetch_domains(
        url,
        allowed=arguments.get("allowed_domains"),
        blocked=arguments.get("blocked_domains"),
    )
    result = web_fetch(
        url,
        format=str(arguments.get("format") or "markdown"),
        timeout_s=20.0,
        on_output=getattr(_context, "report_output", None),
        on_progress=getattr(_context, "report_progress", None),
    )
    return apply_fetch_content_budget(result, arguments.get("max_content_tokens"))


def _task_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task 原生 handler：整表替换会话规划，并回传前端抽屉所需的真实步骤。"""
    from .dispatch import build_task_plan
    from .session_board import replace_plan_steps

    plan = build_task_plan(arguments)
    board = getattr(context, "session_tasks", None)
    if isinstance(board, list):
        replace_plan_steps(
            board,
            subject=plan.description or plan.goal[:24],
            description=plan.goal,
            steps=list(plan.steps),
        )
    return plan


def _board_from_context(context: object | None) -> list:
    """取出当前波次共享的会话看板；缺失时用空列表（不写回图状态）。"""
    board = getattr(context, "session_tasks", None)
    return board if isinstance(board, list) else []


def _session_task_create_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """会话看板创建一项，返回 task.id。"""
    from .session_board import BoardToolResult, create_task

    item = create_task(_board_from_context(context), arguments)
    return BoardToolResult("已创建会话任务", item)


def _session_task_get_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """按 taskId 读取看板项。"""
    from .session_board import BoardToolResult, get_task

    item = get_task(_board_from_context(context), str(arguments.get("taskId") or ""))
    if item is None:
        return BoardToolResult("任务不存在", {"task": None})
    return BoardToolResult("已读取会话任务", item)


def _session_task_update_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """更新看板项状态或字段。"""
    from .session_board import BoardToolResult, update_task

    item = update_task(
        _board_from_context(context),
        arguments,
        owner=str(getattr(context, "user_id", "") or ""),
    )
    return BoardToolResult("已更新会话任务", item)


def _session_task_list_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """列出未删除的会话任务。"""
    from .session_board import BoardToolResult, list_tasks

    items = list_tasks(_board_from_context(context))
    return BoardToolResult(
        f"当前清单 {len(items)} 项",
        {"tasks": items},
        model_text=f"会话任务 {len(items)} 项",
    )


def _ask_user_question_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """提问在 ToolNode 内 interrupt；handler 不应被走到。"""
    raise AppError(ErrorCode.INTERNAL, "ask_user_question 必须由 ToolNode 挂起")


def _bash_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """bash 工具 handler：runner 容器内按网络模式执行（阶段 3 开放通用 bash）。

    资源限制读 Settings（内存/进程数/CPU），``sandbox_dir`` 由平台注入，
    禁止模型传参（M5-D7 红线）；无字符串词表/静态裁决——``mode`` 声明网络模式
    （isolated 断网 / network 保留网络），文件边界由容器挂载与权限档位审批承担；
    引擎为 "off" 或 runner 不可用时 fail-closed（VALIDATION），禁止降级为无隔离执行。
    """
    from app.config import settings
    from app.harness.execution.dispatch import BashResult, run_bash
    from app.harness.execution.sandbox import SandboxLimits
    from app.harness.security.exec_policy import resolve_bash_engine

    # #5：沙箱引擎决策收敛于 exec_policy.resolve_bash_engine（显式 Spec 决策，
    # 非 container 一律 fail-closed，禁止降级无隔离执行）
    verdict = resolve_bash_engine(settings.sandbox_engine)
    if not verdict.allow:
        raise AppError(ErrorCode.VALIDATION, verdict.reason)
    limits = SandboxLimits(
        memory_kb=settings.sandbox_memory_mb * 1024,
        nproc=settings.sandbox_nproc,
        cpu_s=settings.sandbox_cpu_s,
    )
    from .aliases import bash_timeout_seconds

    started = time.perf_counter()
    # 网络模式来源接缝——上下文（会话档位派生）优先，缺省回落全局 settings。
    mode = str(getattr(context, "sandbox_mode", "") or "") or settings.sandbox_bash_default_mode
    if sandbox_dir:
        # F5/G6（§6.6）：bash 工作区可写，写前容量检查（卷水位熔断优先）。
        from .quota import check_workspace_write_capacity

        check_workspace_write_capacity(sandbox_dir, extra_bytes=0)
    output = run_bash(
        str(arguments.get("command", "")),
        sandbox_dir=sandbox_dir or "",
        mode=mode,
        timeout_s=bash_timeout_seconds(arguments),
        limits=limits,
        on_output=getattr(context, "report_output", None),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return BashResult(output, duration_ms=duration_ms)


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
