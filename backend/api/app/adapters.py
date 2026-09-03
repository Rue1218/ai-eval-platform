"""三协议统一适配器（PRD 6.2 / 后端开发计划 M1 W3）。

统一入口 ``call_protocol``：入参为 ``messages`` 对话列表与采样参数，
出参统一为 ``AdapterResult(text, usage, raw, latency_ms)``。三种协议的
端点、鉴权头与响应结构差异全部在模块内消化：

- ``openai_chat``        POST ``{base}/v1/chat/completions``   ``Authorization: Bearer``
- ``openai_responses``   POST ``{base}/v1/responses``          ``Authorization: Bearer``
- ``anthropic_messages`` POST ``{base}/v1/messages``           ``x-api-key`` + ``anthropic-version``

失败语义统一归一为 ``AppError``：上游 4xx/5xx 与连接错误 → ``UPSTREAM``，
超时 → ``TIMEOUT``，响应结构异常 → ``UPSTREAM``；异常信息绝不携带 API Key。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import anthropic
import openai
from anthropic import Anthropic
from openai import OpenAI

from .config import settings
from .errors import AppError, ErrorCode

if TYPE_CHECKING:
    # 仅类型检查可见：运行时导入会经 app.llm.__init__ → gateway → adapters
    # 形成循环，注解在 future annotations 下字符串化，无需运行时类型。
    from .llm.contracts import SystemSegment

# 契约支持的三种协议（与 protocol_profiles 的 CHECK 约束一致）
SUPPORTED_PROTOCOLS = ("openai_chat", "openai_responses", "anthropic_messages")

# 非流式调用被测 / Agent 模型的默认超时秒数
DEFAULT_TIMEOUT_S = 30.0
# 仅对已知支持 reasoning 控制的模型发送 OpenAI 专用字段，避免普通模型因未知字段报错。
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")
_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def _adapt_message_content(content: object, protocol: str) -> object:
    """把 Agent 内部内容块转换成目标协议的图文消息格式。"""
    if not isinstance(content, list):
        return content
    result: list[dict[str, object]] = []
    for part in content:
        if not isinstance(part, Mapping):
            continue
        kind = part.get("type")
        if kind == "text":
            text = str(part.get("text") or "")
            if protocol == "openai_responses":
                result.append({"type": "input_text", "text": text})
            else:
                result.append({"type": "text", "text": text})
            continue
        if kind != "image_url" or not isinstance(part.get("image_url"), Mapping):
            continue
        url = str(part["image_url"].get("url") or "")
        if not url:
            continue
        if protocol == "anthropic_messages" and url.startswith("data:"):
            header, encoded = url.split(",", 1)
            media_type = header[5:].split(";", 1)[0] or "image/jpeg"
            result.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded,
                    },
                }
            )
        elif protocol == "openai_responses":
            result.append({"type": "input_image", "image_url": url})
        else:
            result.append({"type": "image_url", "image_url": {"url": url}})
    return result


def _tool_call_arguments(raw: object) -> dict[str, object]:
    """把上游函数参数归一为对象，拒绝无效 JSON 而不猜测执行参数。"""
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    if raw in (None, ""):
        return {}
    if not isinstance(raw, str):
        raise ValueError("工具参数不是 JSON 对象")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("工具参数不是 JSON 对象")
    return {str(key): value for key, value in parsed.items()}


def _internal_tool_calls(message: Mapping[str, object]) -> list[dict[str, object]]:
    """提取 Harness 规范的工具调用消息，过滤不完整项目。"""
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list | tuple):
        return []
    calls: list[dict[str, object]] = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            continue
        call_id = str(raw.get("call_id") or raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        arguments = raw.get("arguments")
        if not call_id or not name:
            continue
        try:
            calls.append(
                {
                    "call_id": call_id,
                    "name": name,
                    "arguments": _tool_call_arguments(arguments),
                }
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return calls


def _adapt_messages(messages: list[dict], protocol: str) -> list[dict]:
    """把 Harness 消息映射为三协议的图文与 ToolCall/ToolResult 结构。

    内部规范只使用 ``assistant.tool_calls`` 与 ``role=tool`` 两种表示；
    本函数在边界转换为各供应商的不同字段，调用方无需感知协议差异。
    """
    adapted: list[dict] = []
    anthropic_tool_results: list[dict[str, object]] = []

    def flush_anthropic_tool_results() -> None:
        """把同一 assistant 的多个 ToolResult 合并为一条 user 消息。"""
        if anthropic_tool_results:
            adapted.append({"role": "user", "content": list(anthropic_tool_results)})
            anthropic_tool_results.clear()

    for message in messages:
        role = str(message.get("role") or "user")
        calls = _internal_tool_calls(message)
        content = message.get("content")

        if role == "tool":
            call_id = str(message.get("tool_call_id") or "").strip()
            if not call_id:
                continue
            if protocol == "openai_responses":
                adapted.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": str(content or ""),
                    }
                )
            elif protocol == "anthropic_messages":
                anthropic_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": str(content or ""),
                    }
                )
            else:
                adapted.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": str(content or ""),
                    }
                )
            continue

        if protocol == "anthropic_messages":
            flush_anthropic_tool_results()

        if calls and role == "assistant":
            if protocol == "openai_responses":
                if content:
                    adapted.append(
                        {
                            "role": "assistant",
                            "content": _adapt_message_content(content, protocol),
                        }
                    )
                adapted.extend(
                    {
                        "type": "function_call",
                        "call_id": call["call_id"],
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    }
                    for call in calls
                )
                continue
            if protocol == "anthropic_messages":
                blocks: list[object] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                blocks.extend(
                    {
                        "type": "tool_use",
                        "id": call["call_id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    }
                    for call in calls
                )
                adapted.append({"role": "assistant", "content": blocks})
                continue
            adapted.append(
                {
                    "role": "assistant",
                    "content": _adapt_message_content(content, protocol),
                    "tool_calls": [
                        {
                            "id": call["call_id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                            },
                        }
                        for call in calls
                    ],
                }
            )
            continue

        item = dict(message)
        item.pop("tool_calls", None)
        item["content"] = _adapt_message_content(content, protocol)
        adapted.append(item)
    if protocol == "anthropic_messages":
        flush_anthropic_tool_results()
    return adapted


def _adapt_tools(tools: list[dict] | None, protocol: str) -> list[dict]:
    """把内部 JSON Schema 工具定义映射为三种原生 ToolCall 描述。"""
    adapted: list[dict] = []
    for definition in tools or []:
        name = str(definition.get("name") or "").strip()
        if not name:
            continue
        description = str(definition.get("description") or "")
        schema = definition.get("parameters_schema") or definition.get("parameters") or {
            "type": "object",
            "properties": {},
        }
        if not isinstance(schema, Mapping):
            continue
        parameters = dict(schema)
        if protocol == "openai_chat":
            adapted.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        elif protocol == "openai_responses":
            adapted.append(
                {
                    "type": "function",
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                }
            )
        else:
            adapted.append(
                {
                    "name": name,
                    "description": description,
                    "input_schema": parameters,
                }
            )
    return adapted


def _is_openai_reasoning_model(model: str) -> bool:
    """判断模型名是否属于 OpenAI/o 系列或明确的推理模型。"""
    normalized = model.strip().lower()
    return normalized.startswith(_OPENAI_REASONING_PREFIXES) or any(
        marker in normalized for marker in ("reasoner", "reasoning", "deepseek-r1")
    )


def _openai_reasoning_effort(model: str, enabled: bool, effort: str) -> str | None:
    """返回可发送的 OpenAI effort；普通模型不携带推理专用字段。"""
    # CursorAPI 将模型可选项编码在 ``model[param=value]`` 中，并不会读取
    # OpenAI 请求体的 reasoning_effort；检测到该规格时保留模型名原样透传。
    if "[" in model and model.rstrip().endswith("]"):
        return None
    if not _is_openai_reasoning_model(model):
        return None
    if enabled and effort in _REASONING_EFFORTS:
        return effort
    # 当前新一代 GPT-5/o4 模型支持 none；老模型关闭时仅由网关过滤摘要。
    normalized = model.strip().lower()
    if normalized.startswith(("gpt-5", "o4")):
        return "none"
    return None


def _apply_openai_reasoning(
    body: dict,
    *,
    model: str,
    enabled: bool,
    effort: str,
    responses: bool,
) -> None:
    """按 Chat Completions / Responses 的字段差异写入推理控制参数。"""
    selected = _openai_reasoning_effort(model, enabled, effort)
    if selected is None:
        return
    if responses:
        body["reasoning"] = {"effort": selected}
        if enabled:
            # Responses API 返回的是可展示的 reasoning summary，而非隐藏思维链。
            body["reasoning"]["summary"] = "auto"
    else:
        body["reasoning_effort"] = selected


def _apply_compatible_thinking(
    body: dict,
    base: str,
    model: str,
    enabled: bool,
    effort: str = "medium",
) -> None:
    """为已知 OpenAI 兼容推理端点设置 thinking 开关。"""
    target = f"{base} {model}".lower()
    if "xiaomimimo" in target:
        body["thinking"] = {"type": "enabled" if enabled else "disabled"}
        return

    # Gemini 的 OpenAI 兼容接口不会仅凭模型名把思考摘要放进流；必须
    # 显式传入 Google 扩展字段。这里使用 REST 请求所需的 extra_body
    # 结构，避免把供应商专用字段误发给普通 OpenAI 兼容模型。
    if "gemini" in model.strip().lower() and enabled:
        level = {
            "low": "low",
            "medium": "medium",
            "high": "high",
            # 平台的更高档位映射为 Gemini 支持的最高 thinking_level。
            "xhigh": "high",
            "max": "high",
        }.get(effort, "medium")
        body["extra_body"] = {
            "google": {
                "thinking_config": {
                    "thinking_level": level,
                    "include_thoughts": True,
                }
            }
        }


def _anthropic_thinking_budget(max_tokens: int, effort: str) -> int:
    """把平台强度映射为 Anthropic thinking budget，并限制在输出预算内。"""
    ratio = {"low": 0.2, "medium": 0.4, "high": 0.6, "xhigh": 0.75, "max": 0.8}.get(effort, 0.4)
    return max(256, min(max_tokens - 1, round(max_tokens * ratio)))


def _supports_anthropic_thinking(model: str) -> bool:
    """仅对已知支持 extended thinking 的 Claude 型号发送 thinking 字段。"""
    normalized = model.strip().lower()
    return any(
        marker in normalized
        for marker in ("claude-3-7", "claude-sonnet-4", "claude-opus-4", "claude-haiku-4")
    )


class StreamAborted(Exception):
    """本地取消令牌在读上游时触发；由调用层转成 TurnCancelled，不发给浏览器。"""


@dataclass(frozen=True)
class AdapterToolCall:
    """协议适配器输出的原生工具调用（不依赖 LangGraph 契约包）。"""

    call_id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class AdapterStreamEvent:
    """流式适配器的内部事件；工具调用只在参数完整后发出。"""

    kind: str
    text: str = ""
    tool_call: AdapterToolCall | None = None


@dataclass(frozen=True)
class AdapterResult:
    """三协议统一调用结果。

    ``usage`` 已归一为 ``prompt_tokens / completion_tokens / total_tokens``
    （上游缺失时按 0 计）；``raw`` 保留上游原始 JSON 对象，供报告与调试
    使用，消费方序列化落库时按契约截断到 32KB。
    """

    text: str
    usage: dict
    raw: dict
    latency_ms: int
    tool_calls: tuple[AdapterToolCall, ...] = field(default_factory=tuple)


def _close_quietly(response: object) -> None:
    """取消或超时时关掉上游连接，忽略二次 close 异常。"""
    closer = getattr(response, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            return


def _openai_client(*, base_url: str, api_key: str, timeout_s: float) -> OpenAI:
    """创建单次 OpenAI SDK 客户端，显式关闭 SDK 默认重试以保持调用语义。"""
    return OpenAI(
        api_key=api_key,
        # SDK 的资源路径本身不含版本段，因此在已规范化的服务根地址后补 /v1。
        base_url=f"{base_url.rstrip('/')}/v1",
        timeout=timeout_s,
        max_retries=0,
    )


def _anthropic_client(*, base_url: str, api_key: str, timeout_s: float) -> Anthropic:
    """创建单次 Anthropic SDK 客户端，避免连接或限流时改变既有重试次数。"""
    return Anthropic(
        api_key=api_key,
        # Anthropic SDK 自身会追加 /v1/messages，故这里只传服务根地址。
        base_url=base_url,
        timeout=timeout_s,
        max_retries=0,
    )


def _sdk_response_dict(response: object) -> dict:
    """把 SDK 的 Pydantic 响应或流事件转换为既有归一化函数可消费的字典。"""
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
    else:
        payload = response
    if not isinstance(payload, Mapping):
        raise TypeError("SDK 响应不是对象")
    return {str(key): value for key, value in payload.items()}


def _ensure_sse_stream(stream: object) -> None:
    """拒绝网关忽略 stream 参数时返回的完整 JSON，避免 SDK 静默产生空迭代。"""
    response = getattr(stream, "response", None)
    headers = getattr(response, "headers", None)
    content_type = headers.get("content-type") if isinstance(headers, Mapping) else None
    if content_type and "text/event-stream" not in str(content_type).lower():
        raise AppError(ErrorCode.UPSTREAM, "上游未返回流式响应")


def _openai_chat_create(client: object, body: dict, *, stream: bool = False) -> object:
    """调用 Chat Completions，并把兼容网关私有字段经 SDK 原样合入请求体。"""
    request = dict(body)
    if stream:
        # ``stream`` 是 SDK 的正式参数，不再作为手写 HTTP JSON 字段传递。
        request["stream"] = True
    vendor_body: dict[str, object] = {}
    if "thinking" in request:
        vendor_body["thinking"] = request.pop("thinking")
    if "extra_body" in request:
        # 当前 Gemini 兼容档要求请求 JSON 中存在字面 ``extra_body`` 字段；
        # SDK 的 extra_body 参数会合并请求体，故此处保留一层同名键。
        vendor_body["extra_body"] = request.pop("extra_body")
    create = client.chat.completions.create  # type: ignore[attr-defined]
    if vendor_body:
        return create(**request, extra_body=vendor_body)
    return create(**request)


def _openai_responses_create(client: object, body: dict, *, stream: bool = False) -> object:
    """调用 Responses API；流式标志通过 SDK 正式参数传入。"""
    request = dict(body)
    if stream:
        request["stream"] = True
    return client.responses.create(**request)  # type: ignore[attr-defined]


def _anthropic_messages_create(
    client: object,
    body: dict,
    anthropic_version: str | None,
    *,
    stream: bool = False,
) -> object:
    """调用 Messages API，并保留协议档指定的 anthropic-version 请求头。"""
    request = dict(body)
    if stream:
        request["stream"] = True
    return client.messages.create(  # type: ignore[attr-defined]
        **request,
        extra_headers={"anthropic-version": anthropic_version or "2023-06-01"},
    )


def _norm_usage(data: dict, *, anthropic: bool) -> dict:
    """把三协议各自的 usage 字段归一为统一 token 与缓存计数结构。

    缓存字段仅在上游明确返回时透传：Anthropic 使用 input token 的读/创建
    计数，OpenAI 使用 ``prompt_tokens_details.cached_tokens``。缺失表示上游
    未提供该观测，不能伪造为命中或零命中。
    """
    usage = data.get("usage") or {}
    if not isinstance(usage, Mapping):
        usage = {}
    if anthropic:
        # Anthropic 使用 input_tokens / output_tokens 命名，total 需自行求和
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)
        normalized = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
        if cache_read or cache_creation:
            normalized.update(
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_creation,
            )
        return normalized
    # OpenAI Chat 与部分兼容网关使用 prompt/completion_tokens；官方
    # Responses 对象使用 input/output_tokens。两种响应均需维持平台统一口径。
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    normalized = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    details = usage.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        cache_read = int(details.get("cached_tokens") or 0)
        if cache_read:
            normalized["cache_read_input_tokens"] = cache_read
    return normalized


def _full_text(protocol: str, data: dict) -> str:
    """从完整（非流式）响应对象中提取全文，供 call_protocol 与流式兜底复用。"""
    if protocol == "openai_chat":
        # 兼容网关在 max_tokens=1 时可能返回 content=None
        choices = data["choices"]
        return str(choices[0]["message"].get("content") or "")
    if protocol == "openai_responses":
        # output 数组内仅拼接 output_text 内容块
        return "".join(
            str(part.get("text") or "")
            for item in data["output"]
            for part in (item.get("content") or [])
            if part.get("type") == "output_text"
        )
    # anthropic_messages：content 数组内仅拼接 text 内容块
    return "".join(str(block.get("text") or "") for block in data["content"] if block.get("type") == "text")


def _new_call_id() -> str:
    """为未提供调用 ID 的兼容端点生成稳定的本轮关联标识。"""
    return f"toolcall_{uuid4().hex}"


def _full_tool_calls(protocol: str, data: dict) -> tuple[AdapterToolCall, ...]:
    """从三协议完整响应提取函数调用并统一参数与调用 ID。"""
    raw_calls: list[tuple[object, object, object]] = []
    if protocol == "openai_chat":
        message = (data.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls and isinstance(message.get("function_call"), Mapping):
            calls = [{"id": "", "function": message["function_call"]}]
        for call in calls:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function") or {}
            if isinstance(function, Mapping):
                raw_calls.append((call.get("id"), function.get("name"), function.get("arguments")))
    elif protocol == "openai_responses":
        for item in data.get("output") or []:
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                raw_calls.append(
                    (item.get("call_id") or item.get("id"), item.get("name"), item.get("arguments"))
                )
    else:
        for block in data.get("content") or []:
            if isinstance(block, Mapping) and block.get("type") == "tool_use":
                raw_calls.append((block.get("id"), block.get("name"), block.get("input")))

    calls: list[AdapterToolCall] = []
    for raw_id, raw_name, raw_arguments in raw_calls:
        name = str(raw_name or "").strip()
        if not name:
            # 少数兼容网关会在普通文本响应里附带不完整的 tool_use 占位块；
            # 它不构成可执行调用，忽略而不是把正常正文升级为上游错误。
            continue
        calls.append(
            AdapterToolCall(
                call_id=str(raw_id or "").strip() or _new_call_id(),
                name=name,
                arguments=_tool_call_arguments(raw_arguments),
            )
        )
    return tuple(calls)


def _complete_stream_tool_call(
    raw_id: object,
    raw_name: object,
    raw_arguments: object,
) -> AdapterToolCall | None:
    """把已累计完成的流式参数转换为可执行调用，拒绝不完整 JSON。"""
    name = str(raw_name or "").strip()
    if not name:
        return None
    try:
        arguments = _tool_call_arguments(raw_arguments)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游工具调用参数结构异常") from exc
    return AdapterToolCall(
        call_id=str(raw_id or "").strip() or _new_call_id(),
        name=name,
        arguments=arguments,
    )


def _service_base_url(base_url: str) -> str:
    """规范化协议服务根地址，智能剥离常见后缀（如 /v1/models、/models、/chat/completions、/messages 等）。

    三种协议的具体端点由本适配器统一追加相应路径段。协议档常见的
    OpenAI 兼容地址通常带 /v1，因此这里会智能剥离末尾的子路径与版本段，
    避免真实请求错误落到 /models/v1/models、/v1/v1/... 等错误地址；不修改数据库中用户保存的原值。
    """
    base = base_url.strip().rstrip("/")
    for suffix in (
        "/chat/completions",
        "/messages",
        "/responses",
        "/models",
        "/v1/models",
        "/v1/chat/completions",
        "/v1/messages",
        "/v1/responses",
        "/api/tags",
        "/api/v1/models",
    ):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    return base


def _anthropic_system_param(
    system: str | None,
    segments: tuple[SystemSegment, ...] | None = None,
    *,
    cache_enabled: bool = False,
) -> str | list[dict[str, object]]:
    """Anthropic Messages 的 system 参数：缓存边界开启时返回带断点的内容块数组。

    ADR-5：断点只落在**最后一个可缓存静态段**（S1 Persona / S2 Skill Hint /
    S4 Skill 工作流），动态段（S6 会话摘要、S7 当轮输入）位于断点之后随请求
    发送但不计入缓存前缀。不满足条件（开关关 / 无分段）时返回原字符串，
    行为与骨架化版本一致。``cache_control`` 由协议档 anthropic-version
    （2023-06-01 起支持）承载；上游不支持时错误归一兜底，调用方可关闭开关。
    OpenAI 系协议依赖自动前缀缓存，仅需保证前缀字节级稳定，不做本处理。
    """
    if not cache_enabled or not segments:
        return system or ""
    blocks: list[dict[str, object]] = []
    last_cacheable: int | None = None
    for index, segment in enumerate(segments):
        if segment.cacheable and segment.text:
            last_cacheable = index
    for index, segment in enumerate(segments):
        if not segment.text:
            continue
        block: dict[str, object] = {"type": "text", "text": segment.text}
        if index == last_cacheable:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


def _prompt_cache_flag(prompt_cache: bool | None) -> bool:
    """缓存开关判定：显式传入优先，否则读运行配置（默认关闭）。"""
    return settings.prompt_cache_enabled if prompt_cache is None else prompt_cache


def call_protocol(
    *,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
    anthropic_version: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    reasoning_enabled: bool = False,
    reasoning_effort: str = "medium",
    tools: list[dict] | None = None,
    system_segments: tuple[SystemSegment, ...] | None = None,
    prompt_cache: bool | None = None,
) -> AdapterResult:
    """按协议适配调用上游模型并返回统一结构的结果对象。

    ``messages`` 为 ``[{"role": "user" | "assistant", "content": "..."}]``；
    系统提示词经 ``system`` 独立传入，由各协议以自身字段承载
    （chat 的 system 消息 / responses 的 instructions / anthropic 的 system）。
    """
    if protocol not in SUPPORTED_PROTOCOLS:
        raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{protocol}")

    base = _service_base_url(base_url)
    client: object | None = None

    if protocol == "openai_chat":
        chat: list[dict] = ([{"role": "system", "content": system}] if system else []) + _adapt_messages(messages, protocol)
        body: dict = {
            "model": model,
            "messages": chat,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        native_tools = _adapt_tools(tools, protocol)
        if native_tools:
            body["tools"] = native_tools
        # 非流式调用默认关闭 Mimo 思考，避免规划 JSON 被 reasoning 占满；Agent
        # 若显式打开则由 ModelGateway 传入 reasoning_enabled=True。
        _apply_compatible_thinking(body, base, model, reasoning_enabled, reasoning_effort)
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=False,
        )
    elif protocol == "openai_responses":
        body = {"model": model, "input": _adapt_messages(messages, protocol), "max_output_tokens": max_tokens}
        native_tools = _adapt_tools(tools, protocol)
        if native_tools:
            body["tools"] = native_tools
        if system:
            body["instructions"] = system
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=True,
        )
    else:  # anthropic_messages
        body = {
            "model": model,
            "messages": _adapt_messages(messages, protocol),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        native_tools = _adapt_tools(tools, protocol)
        if native_tools:
            body["tools"] = native_tools
        if system:
            body["system"] = _anthropic_system_param(
                system,
                system_segments,
                cache_enabled=_prompt_cache_flag(prompt_cache),
            )
        if reasoning_enabled and _supports_anthropic_thinking(model):
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": _anthropic_thinking_budget(max_tokens, reasoning_effort),
            }
            # Anthropic extended thinking 要求 temperature 使用默认值 1。
            body["temperature"] = 1.0
    started = time.perf_counter()
    try:
        if protocol == "openai_chat":
            client = _openai_client(base_url=base, api_key=api_key, timeout_s=timeout_s)
            response = _openai_chat_create(client, body)
        elif protocol == "openai_responses":
            client = _openai_client(base_url=base, api_key=api_key, timeout_s=timeout_s)
            response = _openai_responses_create(client, body)
        else:
            client = _anthropic_client(base_url=base, api_key=api_key, timeout_s=timeout_s)
            response = _anthropic_messages_create(client, body, anthropic_version)
        data = _sdk_response_dict(response)
    except (openai.APITimeoutError, anthropic.APITimeoutError) as exc:
        raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
    except (openai.APIStatusError, anthropic.APIStatusError) as exc:
        # 仅回显状态码，绝不把请求头（含 Key）或上游原文带给浏览器。
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.status_code}") from exc
    except (openai.APIConnectionError, anthropic.APIConnectionError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc
    except (openai.APIError, anthropic.APIError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游调用失败") from exc
    finally:
        if client is not None:
            _close_quietly(client)

    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        text = _full_text(protocol, data)
        tool_calls = _full_tool_calls(protocol, data)
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常") from exc

    return AdapterResult(
        text=text,
        usage=_norm_usage(data, anthropic=protocol == "anthropic_messages"),
        raw=data,
        latency_ms=latency_ms,
        tool_calls=tool_calls,
    )


def stream_protocol(
    *,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
    anthropic_version: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    should_abort: Callable[[], bool] | None = None,
    reasoning_enabled: bool = True,
    reasoning_effort: str = "medium",
    tools: list[dict] | None = None,
    system_segments: tuple[SystemSegment, ...] | None = None,
    prompt_cache: bool | None = None,
) -> Iterator[tuple[str, str] | AdapterStreamEvent]:
    """按协议流式调用上游模型，逐块 yield ``(kind, text)`` 增量。

    ``kind`` 为增量类别：``"content"`` 是正式回复正文，``"reasoning"``
    是推理模型的前置思考链（deepseek 风格 ``reasoning_content`` /
    anthropic ``thinking_delta`` / responses ``reasoning_summary``），
    供前端思考卡展示；上游未产生思考链时全程只 yield content。

    SDK 负责 SSE 建连、解帧与事件反序列化；适配器只消费 SDK 的事件对象，
    所以不再持有手写 ``urlopen``、逐行读取或非 SSE 重解析逻辑。``timeout_s``
    同时配置给 SDK 并约束本地事件循环的总时长；超时归一为 TIMEOUT，上游
    4xx/5xx 与流式解码失败归一为 UPSTREAM。原生工具参数会在适配器内累积，
    只有完整 JSON 才以 ``AdapterStreamEvent(tool_call)`` 发出。
    """
    if protocol not in SUPPORTED_PROTOCOLS:
        raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{protocol}")

    base = _service_base_url(base_url)
    def complete_stream_call(
        raw_id: object, raw_name: object, raw_arguments: object
    ) -> list[AdapterToolCall]:
        """把单项完成调用包装为列表，便于三个协议统一消费。"""
        call = _complete_stream_tool_call(raw_id, raw_name, raw_arguments)
        return [call] if call is not None else []

    def drain_tool_calls(states: dict[str, dict[str, object]]) -> list[AdapterToolCall]:
        """在完成信号或流结束时一次性输出所有已累计调用。"""
        completed: list[AdapterToolCall] = []
        for key in tuple(states):
            state = states.pop(key)
            parts = state.get("arguments")
            raw_arguments = (
                "".join(str(part) for part in parts)
                if isinstance(parts, list)
                else ""
            )
            raw_arguments = raw_arguments or state.get("input")
            completed.extend(
                complete_stream_call(
                    state.get("call_id"), state.get("name"), raw_arguments
                )
            )
        return completed

    if protocol == "openai_chat":
        chat: list[dict] = (
            ([{"role": "system", "content": system}] if system else [])
            + _adapt_messages(messages, protocol)
        )
        body: dict = {
            "model": model,
            "messages": chat,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        native_tools = _adapt_tools(tools, protocol)
        if native_tools:
            body["tools"] = native_tools
        # 流式思考是否开启由 Agent 设置控制；默认值保持 Mimo 旧行为（开启）。
        _apply_compatible_thinking(body, base, model, reasoning_enabled, reasoning_effort)
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=False,
        )

        def delta_of(data: dict) -> tuple[str, str]:
            choices = data.get("choices") or [{}]
            delta = choices[0].get("delta") or {}
            reasoning = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
                or delta.get("thought")
                or delta.get("thinking")
            )
            if reasoning:
                # 推理模型的思考链增量（deepseek/mimo/qwen 等风格）
                return ("reasoning", str(reasoning))
            return ("content", str(delta.get("content") or ""))

        chat_calls: dict[str, dict[str, object]] = {}

        def tool_events_of(data: dict) -> list[AdapterToolCall]:
            """累计 Chat Completions 的 indexed tool_calls，完成信号后再输出。"""
            choices = data.get("choices") or [{}]
            choice = choices[0] if isinstance(choices[0], Mapping) else {}
            delta = choice.get("delta") or {}
            raw_calls = delta.get("tool_calls") if isinstance(delta, Mapping) else None
            if isinstance(raw_calls, list):
                for index, raw_call in enumerate(raw_calls):
                    if not isinstance(raw_call, Mapping):
                        continue
                    key = str(raw_call.get("index", index))
                    state = chat_calls.setdefault(key, {"arguments": []})
                    if raw_call.get("id"):
                        state["call_id"] = raw_call["id"]
                    function = raw_call.get("function") or {}
                    if isinstance(function, Mapping):
                        if function.get("name"):
                            state["name"] = function["name"]
                        arguments = function.get("arguments")
                        if arguments:
                            state["arguments"].append(str(arguments))
            if choice.get("finish_reason") not in {"tool_calls", "function_call"}:
                return []
            return drain_tool_calls(chat_calls)

        def flush_tool_events() -> list[AdapterToolCall]:
            return drain_tool_calls(chat_calls)

    elif protocol == "openai_responses":
        body = {
            "model": model,
            "input": _adapt_messages(messages, protocol),
            "max_output_tokens": max_tokens,
        }
        native_tools = _adapt_tools(tools, protocol)
        if native_tools:
            body["tools"] = native_tools
        if system:
            body["instructions"] = system
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=True,
        )

        def delta_of(data: dict) -> tuple[str, str]:  # noqa: F811  （各分支同名提取器，互斥定义）
            kind = data.get("type")
            if kind == "response.reasoning_summary_text.delta":
                return ("reasoning", str(data.get("delta") or ""))
            if kind == "response.output_text.delta":
                return ("content", str(data.get("delta") or ""))
            return ("content", "")

        response_calls: dict[str, dict[str, object]] = {}

        def tool_events_of(data: dict) -> list[AdapterToolCall]:
            """累计 Responses 函数参数 delta，并优先使用官方 done 事件完成调用。"""
            event_type = str(data.get("type") or "")
            raw_key = data.get("item_id")
            if raw_key is None:
                raw_key = data.get("output_index")
            key = str(raw_key) if raw_key is not None else ""
            if event_type == "response.function_call_arguments.delta" and key:
                state = response_calls.setdefault(key, {"arguments": []})
                if data.get("delta"):
                    state["arguments"].append(str(data["delta"]))
                return []
            if event_type == "response.function_call_arguments.done":
                state = response_calls.pop(key, {})
                return complete_stream_call(
                    data.get("call_id") or state.get("call_id") or key,
                    data.get("name") or state.get("name"),
                    data.get("arguments")
                    if data.get("arguments") is not None
                    else "".join(state.get("arguments", [])),
                )
            if event_type in {"response.output_item.added", "response.output_item.done"}:
                item = data.get("item") or {}
                if isinstance(item, Mapping) and item.get("type") == "function_call":
                    item_key = str(item.get("id") or item.get("call_id") or key)
                    if event_type.endswith("added"):
                        response_calls.setdefault(
                            item_key,
                            {
                                "call_id": item.get("call_id") or item.get("id"),
                                "name": item.get("name"),
                                "arguments": [],
                            },
                        )
                        return []
                    response_calls.pop(item_key, None)
                    return complete_stream_call(
                        item.get("call_id") or item.get("id"),
                        item.get("name"),
                        item.get("arguments"),
                    )
            return []

        def flush_tool_events() -> list[AdapterToolCall]:
            return drain_tool_calls(response_calls)

    else:  # anthropic_messages
        body = {
            "model": model,
            "messages": _adapt_messages(messages, protocol),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        native_tools = _adapt_tools(tools, protocol)
        if native_tools:
            body["tools"] = native_tools
        if system:
            body["system"] = _anthropic_system_param(
                system,
                system_segments,
                cache_enabled=_prompt_cache_flag(prompt_cache),
            )
        if reasoning_enabled and _supports_anthropic_thinking(model):
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": _anthropic_thinking_budget(max_tokens, reasoning_effort),
            }
            body["temperature"] = 1.0

        def delta_of(data: dict) -> tuple[str, str]:  # noqa: F811
            if data.get("type") == "content_block_delta":
                delta = data.get("delta") or {}
                if delta.get("type") == "thinking_delta":
                    return ("reasoning", str(delta.get("thinking") or ""))
                if delta.get("type") == "text_delta":
                    return ("content", str(delta.get("text") or ""))
            return ("content", "")

        anthropic_calls: dict[str, dict[str, object]] = {}

        def tool_events_of(data: dict) -> list[AdapterToolCall]:
            """累计 Anthropic input_json_delta，在 content_block_stop 时完成调用。"""
            event_type = str(data.get("type") or "")
            raw_index = data.get("index")
            index = str(raw_index) if raw_index is not None else ""
            if event_type == "content_block_start":
                block = data.get("content_block") or {}
                if isinstance(block, Mapping) and block.get("type") == "tool_use":
                    anthropic_calls[index] = {
                        "call_id": block.get("id"),
                        "name": block.get("name"),
                        "arguments": [],
                        "input": block.get("input"),
                    }
                return []
            if event_type == "content_block_delta" and index in anthropic_calls:
                delta = data.get("delta") or {}
                if isinstance(delta, Mapping) and delta.get("type") == "input_json_delta":
                    partial = delta.get("partial_json")
                    if partial:
                        anthropic_calls[index]["arguments"].append(str(partial))
                return []
            if event_type == "content_block_stop" and index in anthropic_calls:
                state = anthropic_calls.pop(index)
                raw_arguments = "".join(state.get("arguments", [])) or state.get("input")
                return complete_stream_call(
                    state.get("call_id"), state.get("name"), raw_arguments
                )
            return []

        def flush_tool_events() -> list[AdapterToolCall]:
            return drain_tool_calls(anthropic_calls)

    if should_abort is not None and should_abort():
        raise StreamAborted()

    deadline = time.monotonic() + timeout_s
    client: object | None = None
    stream: object | None = None
    try:
        if protocol == "openai_chat":
            client = _openai_client(base_url=base, api_key=api_key, timeout_s=timeout_s)
            stream = _openai_chat_create(client, body, stream=True)
        elif protocol == "openai_responses":
            client = _openai_client(base_url=base, api_key=api_key, timeout_s=timeout_s)
            stream = _openai_responses_create(client, body, stream=True)
        else:
            client = _anthropic_client(base_url=base, api_key=api_key, timeout_s=timeout_s)
            stream = _anthropic_messages_create(
                client,
                body,
                anthropic_version,
                stream=True,
            )
        _ensure_sse_stream(stream)

        for event in stream:  # type: ignore[union-attr]
            # SDK 只能在流事件边界响应取消；立即关闭其 Stream，避免连接悬挂。
            if should_abort is not None and should_abort():
                _close_quietly(stream)
                raise StreamAborted()
            if time.monotonic() > deadline:
                _close_quietly(stream)
                raise TimeoutError("stream deadline exceeded")

            data = _sdk_response_dict(event)
            kind, text = delta_of(data)
            if text:
                yield (kind, text)
            for tool_call in tool_events_of(data):
                yield AdapterStreamEvent(kind="tool_call", tool_call=tool_call)
    except StreamAborted:
        raise
    except (openai.APITimeoutError, anthropic.APITimeoutError, TimeoutError) as exc:
        raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
    except (openai.APIStatusError, anthropic.APIStatusError) as exc:
        # 仅回显状态码，绝不把请求头（含 Key）或上游原文带给浏览器。
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.status_code}") from exc
    except (openai.APIConnectionError, anthropic.APIConnectionError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc
    except (openai.APIError, anthropic.APIError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游调用失败") from exc
    except OSError as exc:
        # SDK 读连接中断不向浏览器回显原始异常。
        raise AppError(ErrorCode.UPSTREAM, "上游连接中断") from exc
    except (AttributeError, TypeError, ValueError) as exc:
        # SDK 解帧或 Pydantic 转换失败时，不允许把上游原文带给浏览器。
        raise AppError(ErrorCode.UPSTREAM, "上游流式响应结构异常") from exc
    finally:
        if stream is not None:
            _close_quietly(stream)
        if client is not None:
            _close_quietly(client)

    # 少数兼容网关不发送 finish/done 事件；SDK 流自然结束后补齐未完成调用。
    for tool_call in flush_tool_events():
        yield AdapterStreamEvent(kind="tool_call", tool_call=tool_call)


def _anthropic_model_list_roots(base_url: str) -> list[str]:
    """为挂在子路径上的 Anthropic 兼容网关推导宿主根模型列表候选地址。

    DeepSeek（``…/anthropic``）、Kimi、智谱等官方把 Anthropic 协议发布在
    前缀子路径下，``/v1/models`` 模型列表仍位于宿主根或上一级路径；这里只
    生成候选 URL 供逐个尝试，不修改协议档中保存的原值。
    """
    parsed = urlsplit(base_url)
    segments = [seg for seg in parsed.path.split("/") if seg]
    if not segments:
        return []
    origin = f"{parsed.scheme}://{parsed.netloc}"
    roots: list[str] = []
    # 先去掉最后一段得到上一级路径，再回退到宿主根；重复候选由调用方去重。
    for depth in (len(segments) - 1, 0):
        prefix = "/" + "/".join(segments[:depth]) if depth else ""
        candidate = f"{origin}{prefix}"
        if candidate != base_url and candidate not in roots:
            roots.append(candidate)
    return roots


def _remote_model_parameters(item: Mapping[str, object]) -> list[dict[str, object]]:
    """保留上游模型目录声明的可选请求字段，供前端构造模型规格。"""
    raw_parameters = item.get("parameters")
    if not isinstance(raw_parameters, list):
        return []
    parameters: list[dict[str, object]] = []
    for raw_parameter in raw_parameters:
        if not isinstance(raw_parameter, Mapping):
            continue
        parameter_id = str(raw_parameter.get("id") or "").strip()
        raw_values = raw_parameter.get("values")
        if not parameter_id or not isinstance(raw_values, list):
            continue
        values = [str(value) for value in raw_values if isinstance(value, str | int | float | bool)]
        if values:
            parameters.append({"id": parameter_id, "values": values})
    return parameters


def fetch_remote_models(
    *,
    protocol: str,
    base_url: str,
    api_key: str | None = None,
    anthropic_version: str | None = None,
    timeout_s: float = 15.0,
) -> list[dict]:
    """从目标服务端点动态获取可用模型列表（如 /v1/models）。

    统一返回结构：``[{"id": "模型标识", "name": "显示名称", "owned_by": "所属供应商/系统"}]``。
    真实调用远程端点解析实际可用模型，不返回硬编码假数据。
    """
    base = _service_base_url(base_url)
    raw_clean = base_url.strip().rstrip("/")

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ai-eval-platform/1.0",
    }
    if api_key:
        if protocol == "anthropic_messages":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = anthropic_version or "2023-06-01"
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    candidate_urls: list[str] = []
    if protocol == "anthropic_messages":
        candidate_urls = [
            f"{base}/v1/models",
            f"{base}/models",
            f"{base}/api/v1/models",
        ]
        if raw_clean not in candidate_urls:
            candidate_urls.append(raw_clean)
            if not raw_clean.endswith("/models"):
                candidate_urls.append(f"{raw_clean}/models")
        # DeepSeek /anthropic 这类子路径网关通常不在子路径下发布模型列表，
        # 追加宿主根/上一级路径的候选（api.deepseek.com/v1/models 等）。
        for root in _anthropic_model_list_roots(base):
            for path in ("/v1/models", "/models"):
                if f"{root}{path}" not in candidate_urls:
                    candidate_urls.append(f"{root}{path}")
    else:
        candidate_urls = [
            f"{base}/v1/models",
            f"{base}/models",
            f"{base}/api/tags",
            f"{base}/api/v1/models",
        ]
        if raw_clean not in candidate_urls:
            candidate_urls.append(raw_clean)
            if not raw_clean.endswith("/models"):
                candidate_urls.append(f"{raw_clean}/models")

    urls_to_try: list[str] = []
    for u in candidate_urls:
        if u not in urls_to_try and (u.startswith("http://") or u.startswith("https://")):
            urls_to_try.append(u)

    last_error: Exception | None = None
    data: dict | list | None = None
    for url in urls_to_try:
        try:
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout_s) as response:
                raw_bytes = response.read()
                data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                if isinstance(data, dict | list):
                    break
        except HTTPError as exc:
            last_error = exc
            if exc.code in (401, 403):
                raise AppError(ErrorCode.UNAUTHORIZED, f"上游鉴权失败 ({exc.code})，请检查 API Key 凭据") from exc
            continue
        except TimeoutError as exc:
            last_error = exc
            continue
        except URLError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            continue

    models_list: list[dict] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and (item.get("id") or item.get("name") or item.get("display_name")):
                m_id = str(item.get("id") or item.get("name") or item.get("display_name"))
                model_item: dict[str, object] = {
                    "id": m_id,
                    "name": str(item.get("display_name") or item.get("name") or m_id),
                    "owned_by": str(item.get("owned_by") or item.get("root") or ("anthropic" if protocol == "anthropic_messages" else "remote")),
                }
                parameters = _remote_model_parameters(item)
                if parameters:
                    model_item["parameters"] = parameters
                models_list.append(model_item)
    elif isinstance(data, dict):
        raw_items = data.get("data") or data.get("models") or data.get("items") or []
        if isinstance(raw_items, dict) and isinstance(raw_items.get("models"), list):
            raw_items = raw_items["models"]
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict) and (item.get("id") or item.get("name") or item.get("display_name")):
                    m_id = str(item.get("id") or item.get("name") or item.get("display_name"))
                    model_item = {
                        "id": m_id,
                        "name": str(item.get("display_name") or item.get("name") or m_id),
                        "owned_by": str(item.get("owned_by") or item.get("root") or ("anthropic" if protocol == "anthropic_messages" else ("ollama" if "models" in data else "remote"))),
                    }
                    parameters = _remote_model_parameters(item)
                    if parameters:
                        model_item["parameters"] = parameters
                    models_list.append(model_item)

    if models_list:
        # 去重并排序
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for m in models_list:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                deduped.append(m)
        deduped.sort(key=lambda x: x["id"].lower())
        return deduped

    if last_error:
        if isinstance(last_error, HTTPError):
            if last_error.code in (401, 403):
                raise AppError(ErrorCode.UNAUTHORIZED, f"上游鉴权失败 ({last_error.code})，请检查 API Key 凭据") from last_error
            if last_error.code == 404:
                raise AppError(
                    ErrorCode.NOT_FOUND,
                    "目标服务端点未开放模型列表接口 (HTTP 404)。请检查 Base URL 地址或直接在输入框手动填入模型标识名（如 claude-3-7-sonnet-20250219、gpt-4o 等）",
                ) from last_error
            raise AppError(ErrorCode.UPSTREAM, f"上游服务返回 HTTP {last_error.code}，无法获取模型列表") from last_error
        if isinstance(last_error, TimeoutError):
            raise AppError(ErrorCode.TIMEOUT, "获取模型列表超时，请检查服务端点网络") from last_error
        if isinstance(last_error, URLError):
            raise AppError(ErrorCode.UPSTREAM, f"连接上游端点失败: {getattr(last_error, 'reason', last_error)}") from last_error
        raise AppError(ErrorCode.UPSTREAM, f"无法从端点获取模型列表: {last_error}") from last_error
    raise AppError(ErrorCode.UPSTREAM, "端点未返回可解析的模型列表，请检查端点地址或手动输入模型标识名")
