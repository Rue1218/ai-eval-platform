"""模型调用层的稳定输入输出契约。

契约不依赖数据库、FastAPI 或具体模型 SDK。调用方只需要提供模型连接配置与
消息列表，底层协议差异由 ``ModelGateway`` 统一收敛。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

ProtocolName = Literal["openai_chat", "openai_responses", "anthropic_messages"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]
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


Message = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """模型调用请求；消息与系统提示词不参与默认 repr，避免日志泄露正文。"""

    config: ModelConfig
    messages: tuple[Message, ...] = field(default_factory=tuple, repr=False)
    system: str | None = field(default=None, repr=False)
    should_abort: StreamAbort | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_messages(
        cls,
        config: ModelConfig,
        messages: list[Message] | tuple[Message, ...],
        *,
        system: str | None = None,
        should_abort: StreamAbort | None = None,
    ) -> ModelRequest:
        """从普通消息列表构造不可变请求，防止图节点间修改共享输入。"""
        return cls(
            config=config,
            messages=tuple(messages),
            system=system,
            should_abort=should_abort,
        )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """非流式或流式收尾后的统一模型响应。"""

    text: str
    usage: Mapping[str, int] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)
    latency_ms: int = 0


StreamEventKind = Literal["content", "reasoning", "completed"]


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    """LangGraph custom stream 对外投影的最小事件。"""

    kind: StreamEventKind
    text: str = ""
    response: ModelResponse | None = field(default=None, repr=False)
