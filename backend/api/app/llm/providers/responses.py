"""OpenAI Responses 原生异步适配器，复用平台流和协议状态契约。"""

import asyncio
from collections.abc import AsyncIterator

import openai
from shared.responses import ResponsesStream, response_input

from ..loop_contracts import (
    Done,
    LlmRequest,
    ProviderItemEnd,
    ProviderItemStart,
    ReasoningDelta,
    StreamChunk,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    ToolSpec,
    classify_provider_error,
)
from .common import (
    close_async,
    full_url_client_options,
    invalid,
    make_state,
    normalize_base_url,
    plain,
    replay_items,
    usage_values,
    validate_messages,
)
from .options import request_options


def to_responses_input(request: LlmRequest) -> list[dict]:
    """优先完整回放原始 output 项，避免重复追加文本和函数调用。"""
    validate_messages(request.messages)
    wire = []
    for message in request.messages:
        items = replay_items(message, request, request.provider, "openai_responses")
        if items is not None:
            if any(item.get("type") not in {"message", "function_call", "reasoning"} for item in items):
                raise invalid("Responses 历史包含不支持的输出项")
            wire.extend(items)
        else:
            try:
                wire.extend(response_input([message]))
            except (KeyError, TypeError, ValueError) as exc:
                raise invalid("Responses 消息结构不合法") from exc
    return wire


def to_responses_tools(specs: list[ToolSpec]) -> list[dict]:
    """函数定义扁平化；保留现有可选参数语义，不强制开启严格模式。"""
    return [{"type": "function", "name": spec.name, "description": spec.description,
             "parameters": spec.parameters, "strict": False} for spec in specs]


class ResponsesAdapter:
    """绑定单个授权端点，取消任务时释放当前流。"""

    def __init__(self, *, api_key: str, base_url: str | None = None,
                 provider: str = "openai", timeout_s: float = 60.0, full_url: bool = False):
        self._provider = provider
        self._client = openai.AsyncOpenAI(
            api_key=api_key, timeout=timeout_s, max_retries=0,
            base_url=normalize_base_url(base_url, "openai_responses", full_url=full_url) if base_url else None,
            **(full_url_client_options(base_url, asynchronous=True) if full_url and base_url else {}),
        )

    async def close(self) -> None:
        """由回合资源拥有者关闭连接池。"""
        await close_async(self._client)

    async def stream(self, request: LlmRequest) -> AsyncIterator[StreamChunk]:
        """只将供应商明确完成的响应投影为 Done，EOF 保留为中断。"""
        provider = request.provider or self._provider
        kwargs = request_options(request, provider, "openai_responses")
        kwargs.update(model=request.model, input=to_responses_input(request), stream=True, store=False,
                      include=["reasoning.encrypted_content"])
        if request.system:
            kwargs["instructions"] = request.system
        if request.tools:
            kwargs["tools"] = to_responses_tools(request.tools)
        stream = None
        decoder = ResponsesStream()
        try:
            stream = await self._client.responses.create(**kwargs)
            async for event in stream:
                try:
                    parts = decoder.feed(plain(event))
                except (KeyError, TypeError, ValueError) as exc:
                    # 流自身损坏属于响应协议错误，不能归因为用户请求参数被拒绝。
                    raise invalid("Responses 流与完成快照不一致") from exc
                for part in parts:
                    if part[0] == "text":
                        yield TextDelta(part[1])
                    elif part[0] == "reasoning":
                        yield ReasoningDelta(part[1])
                    elif part[0] == "tool_start":
                        yield ToolCallStart(*part[1:])
                    elif part[0] == "tool_delta":
                        yield ToolCallDelta(*part[1:])
            response = decoder.response
            if response is not None:
                items = response["output"]
                # 原始项只进入受控协议状态，不混入可展示文本或工具参数。
                for index, item in enumerate(items):
                    item_id = item.get("id") or f"responses-{index}"
                    yield ProviderItemStart(item_id, index, item["type"])
                    yield ProviderItemEnd(item_id, item)
                state = make_state(request, provider, "openai_responses", items)
                if response["status"] == "incomplete":
                    reason = (response.get("incomplete_details") or {}).get("reason")
                    finish = "length" if reason == "max_output_tokens" else "error:incomplete"
                else:
                    finish = "tool_calls" if decoder.calls else "stop"
                yield Done(finish, usage_values(response.get("usage")), state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from None
        finally:
            if stream is not None:
                await close_async(stream)
