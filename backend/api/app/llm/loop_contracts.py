"""新循环的纯数据契约；保留源 base 的构造顺序与全部公开接口。"""

import hashlib
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from .contracts import SystemSegment

Message = dict[str, Any]
ToolCallDict = dict[str, Any]
ReasoningEffort = Literal["off", "low", "medium", "high", "max", "xhigh"]


class MissingApiKeyError(RuntimeError):
    """授权协议档尚未配置凭据。"""


class LlmRequestError(RuntimeError):
    """供循环确定重试策略的内部错误，不携带上游原文。"""

    def __init__(self, message: str, *, code: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code: int | None = None


class UnsupportedReasoningEffortError(LlmRequestError):
    """当前模型能力无法表达所要求的思考档位。"""

    def __init__(self, provider: str, effort: str):
        super().__init__(
            f"{provider} 不支持思考档位 {effort!r}",
            code="unsupported_reasoning_effort",
            retryable=False,
        )


def is_retryable_error(error: BaseException) -> bool:
    """保留源重试分类，重试次数由循环管理。"""
    if isinstance(error, LlmRequestError):
        return error.retryable
    return isinstance(error, TimeoutError | ConnectionError | OSError)


def classify_provider_error(error: Exception) -> LlmRequestError:
    """归一 SDK 错误；只保留结构化状态码，避免凭据进入事实。"""
    if isinstance(error, LlmRequestError):
        return error
    status = getattr(error, "status_code", None)
    retryable = (
        isinstance(error, TimeoutError | ConnectionError | OSError)
        or type(error).__name__ in {"APIConnectionError", "APITimeoutError"}
        or status == 429
        or isinstance(status, int)
        and status >= 500
    )
    result = LlmRequestError(
        "模型连接失败" if retryable else "模型请求失败",
        code="provider_transport" if retryable else "provider_request",
        retryable=retryable,
    )
    result.status_code = status if isinstance(status, int) else None
    return result


@dataclass(frozen=True)
class ToolSpec:
    """唯一工具注册表投影的 JSON Schema，不改变源 parameters 字段。"""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ProtocolState:
    """完成的供应商状态；可 asdict 落库，禁止放入普通 WS 正文。"""

    version: int = 1
    provider: str = ""
    protocol: str = ""
    model: str = ""
    compatibility_key: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    replay_policy: str = "items_v1"


@dataclass(frozen=True)
class LlmRequest:
    """可持久化请求；前八个参数兼容源，不存连接、密钥或回调。"""

    model: str
    messages: list[Message]
    system: str
    tools: list[ToolSpec]
    max_tokens: int
    provider: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    thinking: bool | None = None
    profile_id: str | None = None
    profile_version: str | int | None = None
    protocol: str | None = None
    system_segments: tuple[SystemSegment, ...] = ()
    temperature: float | None = None
    timeout_s: float | None = None
    reasoning_enabled: bool | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    compatibility_key: str | None = None

    def __post_init__(self) -> None:
        """持久请求禁止任意供应商透传，凭据字段在生成 header 前即被拒绝。"""
        allowed = {
            "prompt_cache",
            "anthropic_version",
            "thinking",
            "reasoning_effort",
            "reasoning",
            "omit_temperature",
            "max_tokens_parameter",
            "google_thinking",
        }
        if not isinstance(self.provider_options, dict) or set(self.provider_options) - allowed:
            raise LlmRequestError("供应商选项含未登记字段", code="model_config")
        shapes = {
            "thinking": {"type", "budget_tokens"},
            "reasoning": {"effort", "summary"},
            "google_thinking": {"thinking_level", "include_thoughts"},
        }
        for name, keys in shapes.items():
            value = self.provider_options.get(name)
            if value is not None and (
                not isinstance(value, dict)
                or set(value) - keys
                or any(isinstance(part, dict | list) for part in value.values())
            ):
                raise LlmRequestError("供应商选项结构不合法", code="model_config")
        for name in ("prompt_cache", "omit_temperature"):
            if name in self.provider_options and not isinstance(self.provider_options[name], bool):
                raise LlmRequestError("供应商开关必须为布尔值", code="model_config")
        for name in ("anthropic_version", "reasoning_effort", "max_tokens_parameter"):
            if name in self.provider_options and not isinstance(self.provider_options[name], str):
                raise LlmRequestError("供应商标识必须为字符串", code="model_config")

    def header(self) -> dict[str, Any]:
        """源字段保持字节级指纹兼容；扩展只记录解析后的非敏感字段。"""
        result: dict[str, Any] = {
            "model": self.model,
            "system": self.system,
            "tools": [asdict(tool) for tool in self.tools],
            "max_tokens": self.max_tokens,
        }
        for name in (
            "provider",
            "reasoning_effort",
            "thinking",
            "profile_id",
            "profile_version",
            "protocol",
            "temperature",
            "timeout_s",
            "reasoning_enabled",
            "compatibility_key",
        ):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        if self.system_segments:
            result["system_segments"] = [asdict(segment) for segment in self.system_segments]
        if self.provider_options:
            result["provider_options"] = deepcopy(self.provider_options)
        return result

    def fingerprint(self) -> str:
        """沿用源哈希算法；历史正文独立由窗口事实重建。"""
        return header_fingerprint(self.header())


def header_fingerprint(header: dict[str, Any]) -> str:
    """源 JSON 序列化及 SHA256 算法，不修改分隔符。"""
    canonical = json.dumps(header, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TextDelta:
    """正文增量。"""

    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    """思考或摘要增量，是否展示由上层授权决定。"""

    text: str


@dataclass(frozen=True)
class ToolCallStart:
    """供应商调用身份；不生成替代 ID。"""

    index: int
    id: str
    name: str


@dataclass(frozen=True)
class ToolCallDelta:
    """原始 JSON 碎片；仅 Attempt 负责解析与结算。"""

    index: int
    arguments_fragment: str


@dataclass(frozen=True)
class ProviderItemStart:
    """内部状态块开始，index 与语义流共享供应商定位。"""

    item_id: str
    index: int
    kind: str


@dataclass(frozen=True)
class ProviderItemDelta:
    """内部原始状态字段增量，禁止重复投影为正文。"""

    item_id: str
    field: str
    fragment: str


@dataclass(frozen=True)
class ProviderItemEnd:
    """完整且可回传的状态块快照。"""

    item_id: str
    item: dict[str, Any]


@dataclass(frozen=True)
class Done:
    """仅真实终止信号生成；未报告的用量字段保持缺省。"""

    finish_reason: str
    usage: dict[str, int] = field(default_factory=dict)
    protocol_state: ProtocolState | None = None


StreamChunk = (
    TextDelta
    | ReasoningDelta
    | ToolCallStart
    | ToolCallDelta
    | Done
    | ProviderItemStart
    | ProviderItemDelta
    | ProviderItemEnd
)


class LlmAdapter(Protocol):
    """一次请求一个异步流；没有重试、工具执行或 WS 副作用。"""

    def stream(self, request: LlmRequest) -> AsyncIterator[StreamChunk]: ...
