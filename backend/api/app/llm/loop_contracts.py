"""新循环的纯数据契约；保留源 base 的构造顺序与全部公开接口。"""

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
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

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool = False,
        public_code: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        # 浏览器只消费平台标准码，内部分类码仅用于重试与诊断。
        self.public_code = public_code or _public_error_code(code)
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


def _public_error_code(code: str) -> str:
    """把模型内部分类压缩为既有平台错误码，避免浏览器依赖供应商细节。"""
    if code in {"model_config", "history_selection", "unsupported_reasoning_effort", "protocol_state_incompatible"}:
        return "VALIDATION"
    return "UPSTREAM"


def _provider_error_terms(error: Exception) -> str:
    """从 SDK 的结构化错误字段提取分类词，绝不把字段内容返回给调用方。"""
    values: list[str] = []
    direct_code = getattr(error, "code", None)
    if isinstance(direct_code, str):
        values.append(direct_code)
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        candidates = [body]
        nested = body.get("error")
        if isinstance(nested, Mapping):
            candidates.append(nested)
        for candidate in candidates:
            for key in ("code", "type", "error_code"):
                value = candidate.get(key)
                if isinstance(value, str):
                    values.append(value)
    return "".join(character for value in values for character in value.casefold() if character.isalnum())


def classify_provider_error(error: Exception) -> LlmRequestError:
    """归一 SDK 错误为可行动的安全摘要，避免凭据与上游原文进入事实。"""
    if isinstance(error, LlmRequestError):
        return error
    status = getattr(error, "status_code", None)
    status = status if isinstance(status, int) and not isinstance(status, bool) else None
    terms = _provider_error_terms(error)
    # 顺序固定：额度耗尽常以 429 返回，必须先于通用限流识别。
    if any(marker in terms for marker in (
        "insufficientquota", "quotaexceeded", "quotaexhausted", "insufficientbalance",
        "balanceinsufficient", "insufficientfunds", "creditbalance", "arrearage",
    )):
        result = LlmRequestError(
            "模型服务额度已用尽，请为当前协议档充值或切换可用模型后重试",
            code="provider_quota", public_code="BUDGET_EXCEEDED",
        )
    elif any(marker in terms for marker in (
        "contextlengthexceeded", "maximumcontextlength", "maxcontextlength", "inputtoolong",
        "requesttoolarge", "toomanytokens", "tokenlimitexceeded",
    )):
        result = LlmRequestError(
            "本轮输入超出模型上下文限制，请缩短消息或减少附件后重试",
            code="provider_context", public_code="VALIDATION",
        )
    elif status in {401, 403} or any(marker in terms for marker in (
        "invalidapikey", "authenticationerror", "authenticationfailed", "permissiondenied", "accessdenied",
    )):
        result = LlmRequestError(
            "模型服务认证失败，请检查当前协议档的 API Key、地址和访问权限",
            code="provider_auth",
        )
    elif status == 404 or any(marker in terms for marker in (
        "modelnotfound", "modelnotexist", "modeldoesnotexist", "unsupportedmodel", "modelnotsupported",
    )):
        result = LlmRequestError(
            "当前模型不可用，请检查模型 ID、区域和账号权限",
            code="provider_model",
        )
    elif status == 429:
        result = LlmRequestError(
            "模型服务请求过于频繁，请稍后重试或降低并发",
            code="provider_rate_limit", retryable=True,
        )
    elif status is not None and status >= 500:
        result = LlmRequestError(
            "模型服务暂时不可用，请稍后重试",
            code="provider_unavailable", retryable=True,
        )
    elif isinstance(error, TimeoutError | ConnectionError | OSError) or type(error).__name__ in {"APIConnectionError", "APITimeoutError"}:
        result = LlmRequestError(
            "模型服务连接失败，请稍后重试",
            code="provider_transport", retryable=True,
        )
    else:
        result = LlmRequestError(
            "模型服务拒绝了本次请求，请检查协议档配置后重试",
            code="provider_request",
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
    # 模板 ID 进入无密钥请求头，确保历史回放可以追溯供应商参数方言。
    reasoning_template_id: str | None = None
    # 平台收尾专用：保留历史工具定义，只禁止本次生成新的工具调用。
    tool_choice: Literal["none"] | None = None

    def __post_init__(self) -> None:
        """持久请求禁止任意供应商透传，凭据字段在生成 header 前即被拒绝。"""
        if self.tool_choice not in (None, "none"):
            raise LlmRequestError("工具选择策略不合法", code="model_config")
        allowed = {
            "prompt_cache",
            "anthropic_version",
            "thinking",
            "output_config",
            "reasoning_effort",
            "reasoning",
            "omit_temperature",
            "max_tokens_parameter",
            "google_thinking",
            "enable_thinking", "thinking_budget", "chat_template_kwargs", "reasoning_split",
        }
        if not isinstance(self.provider_options, dict) or set(self.provider_options) - allowed:
            raise LlmRequestError("供应商选项含未登记字段", code="model_config")
        if self.reasoning_template_id is not None and not isinstance(self.reasoning_template_id, str):
            raise LlmRequestError("思考模板标识不合法", code="model_config")
        shapes = {
            "thinking": {"type", "budget_tokens"},
            "output_config": {"effort"},
            "reasoning": {"effort", "summary"},
            "google_thinking": {"thinking_level", "thinking_budget", "include_thoughts"},
            "chat_template_kwargs": {"enable_thinking"},
        }
        for name, keys in shapes.items():
            value = self.provider_options.get(name)
            if value is not None and (
                not isinstance(value, dict)
                or set(value) - keys
                or any(isinstance(part, dict | list) for part in value.values())
            ):
                raise LlmRequestError("供应商选项结构不合法", code="model_config")
        for name in ("prompt_cache", "omit_temperature", "enable_thinking", "reasoning_split"):
            if name in self.provider_options and not isinstance(self.provider_options[name], bool):
                raise LlmRequestError("供应商开关必须为布尔值", code="model_config")
        if "thinking_budget" in self.provider_options and (
            type(self.provider_options["thinking_budget"]) is not int
            or self.provider_options["thinking_budget"] < 0
        ):
            raise LlmRequestError("思考预算必须为非负整数", code="model_config")
        # 百炼数值方言允许 1～100 的整数；bool 不能冒充整数，仍拒绝任意对象透传。
        value = self.provider_options.get("reasoning_effort")
        if value is not None and not (isinstance(value, str) or (type(value) is int and 1 <= value <= 100)):
            raise LlmRequestError("思考强度必须为枚举字符串或 1～100 的整数", code="model_config")
        for name in ("anthropic_version", "max_tokens_parameter"):
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
            "reasoning_template_id",
            "tool_choice",
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
    # 可选公开正文分段快照；与模型回放的原始协议状态分离。
    text_parts: list[dict] | None = None
    # 流式阶段只发送定位元数据，避免每个 token 重传完整正文快照。
    output_index: int | None = None
    phase: str | None = None


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
