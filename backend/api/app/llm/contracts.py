"""模型调用层的稳定输入输出契约。

契约不依赖数据库、FastAPI 或具体模型 SDK。调用方只需要提供模型连接配置与
消息列表，底层协议差异由 ``ModelGateway`` 统一收敛。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

ProtocolName = Literal["openai_chat", "anthropic_messages"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]
ToolCallMode = Literal["native", "legacy"]
# 流式取消回调；仅经 RunnableConfig.configurable 注入（O-12 迁移），不入任何 State
StreamAbort = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """一次模型调用的连接与采样配置。

    API Key 只用于发起上游请求，禁止写入日志、事件或对外响应；``repr`` 也不
    展示密钥，避免调试输出意外泄露。
    """

    protocol: ProtocolName
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)
    anthropic_version: str | None = None
    temperature: float = 0.2
    max_tokens: int = 8192
    timeout_s: float = 60.0
    # 是否请求并向上层投影模型返回的思考摘要；不等同于暴露隐藏思维链。
    reasoning_enabled: bool = True
    reasoning_effort: ReasoningEffort = "medium"
    # F0/P3（方案 V0.4 裁决）：上游 tools 装配与档级放行由三态许可承担
    # （settings.agent_native_tools_enabled × agent_native_tools_profile_ids，
    # 见 harness/execution/native_tools_policy.py——装配唯一消费点），本字段不再
    # 承担 tools 发送语义（历史注释"人工验证才发 tools"已废止）。现仅作协议档
    # 能力标记：legacy = 无原生首轮流式（stream_policy.native_stream_allowed
    # 要求 native），native = 默认（可流式/可装配，视装配闸门）。
    tool_call_mode: ToolCallMode = "native"
    full_url: bool = False  # 禁用 SDK 的版本及资源路径补全。


Message = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SystemSegment:
    """系统提示词分段（缓存边界，ADR-5）。

    ``text`` 为段正文；``cacheable`` 标记该段是否为可缓存静态段（静态在前的
    单调段序由 ``assembly.assemble_segments`` 强制，适配器据此决定断点落点）。
    """

    text: str
    cacheable: bool = False


@dataclass(frozen=True, slots=True)
class NativeToolCall:
    """模型协议原生函数调用的统一投影。

    ``call_id`` 由上游返回；兼容端点省略时由适配器生成平台唯一值。该标识
    必须原样贯穿 ToolNode、``tool_call``/``tool_result`` 事件和下一轮
    ``tool`` 消息，禁止再用工具名猜测配对关系。
    """

    call_id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """模型调用请求；消息与系统提示词不参与默认 repr，避免日志泄露正文。

    纯数据契约（不含 ``should_abort`` 回调——回调已迁移至
    ``RunnableConfig.configurable["abort"]["should_abort"]``，见 M4 §3.4）。
    """

    config: ModelConfig
    messages: tuple[Message, ...] = field(default_factory=tuple, repr=False)
    system: str | None = field(default=None, repr=False)
    # 缓存边界分段（ADR-5，H0）：非空且开关开启时适配器按分段落 cache_control；
    # 为空或开关关闭时退化为 system 单字符串，行为与骨架化版本一致。
    system_segments: tuple[SystemSegment, ...] = field(default_factory=tuple, repr=False)
    tools: tuple[Mapping[str, object], ...] = field(
        default_factory=tuple, repr=False
    )  # M2 assemble 产出的工具定义（CX-5）

    @classmethod
    def from_messages(
        cls,
        config: ModelConfig,
        messages: list[Message] | tuple[Message, ...],
        *,
        system: str | None = None,
        tools: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None = None,
    ) -> ModelRequest:
        """从普通消息列表构造不可变请求，防止图节点间修改共享输入。"""
        return cls(
            config=config,
            messages=tuple(messages),
            system=system,
            tools=tuple(tools or ()),
        )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """非流式或流式收尾后的统一模型响应。"""

    text: str
    usage: Mapping[str, int] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)
    latency_ms: int = 0
    tool_calls: tuple[NativeToolCall, ...] = field(default_factory=tuple)


StreamEventKind = Literal["content", "reasoning", "tool_call", "completed"]


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    """LangGraph custom stream 对外投影的最小事件。"""

    kind: StreamEventKind
    text: str = ""
    response: ModelResponse | None = field(default=None, repr=False)
    tool_call: NativeToolCall | None = field(default=None, repr=False)
