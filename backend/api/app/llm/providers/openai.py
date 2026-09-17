"""源 AsyncOpenAI 流骨架，补平台图文、配置与原始工具消息回填。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import openai

from ..loop_contracts import (
    Done,
    LlmRequest,
    Message,
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
    call_arguments,
    close_async,
    content_parts,
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
from .reasoning_templates import is_newapi_template


def to_openai_messages(
    messages: list[Message],
    system: str,
    *,
    include_reasoning_content: bool = False,
    request: LlmRequest | None = None,
) -> list[dict[str, Any]]:
    """源 args/raw 字段直译为函数调用；坏 JSON 原串保留供模型修正。"""
    validate_messages(messages)
    if request is None and any(message.get("protocol_state") is not None for message in messages):
        raise invalid("Chat 消息不能静默删除其他协议的状态")
    wire = [{"role": "system", "content": system}] if system else []
    for message in messages:
        role = message["role"]
        item = {
            "role": role,
            "content": content_parts(message.get("content", ""), "openai_chat", role=role),
        }
        if role == "tool":
            item["tool_call_id"] = message["tool_call_id"]
        elif role == "assistant":
            if message.get("tool_calls"):
                item["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call_arguments(call)},
                    }
                    for call in message["tool_calls"]
                ]
            items = replay_items(message, request, request.provider, "openai_chat") if request else None
            if items:
                if request.provider != "minimax" or len(items) != 1 or items[0].get("type") != "minimax_reasoning":
                    raise invalid("Chat 协议不接受其他供应商原始状态")
                details = items[0].get("details")
                if not isinstance(details, list) or not all(isinstance(d, dict) for d in details):
                    raise invalid("MiniMax 思考状态不合法")
                item["reasoning_details"] = details
            if include_reasoning_content and isinstance(message.get("reasoning_content"), str):
                item["reasoning_content"] = message["reasoning_content"]
        wire.append(item)
    return wire


def to_openai_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """保留源工具 schema 映射。"""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in specs
    ]


def deepseek_request_overrides(request: LlmRequest) -> dict[str, Any]:
    """保留源公开辅助函数，medium 原样透传而非降档。"""
    if request.reasoning_effort == "off":
        return {"thinking": {"type": "disabled"}}
    if request.reasoning_effort in ("low", "medium", "high", "max"):
        return {"thinking": {"type": "enabled"}, "reasoning_effort": request.reasoning_effort}
    if request.thinking is not None:
        return {"thinking": {"type": "enabled" if request.thinking else "disabled"}}
    return {}


def normalize_openai_finish_reason(reason: str) -> str:
    """保留源 length，未知原因不得伪装正常停止。"""
    return {"stop": "stop", "tool_calls": "tool_calls", "length": "length"}.get(
        reason, f"error:{reason}"
    )


class OpenAiAdapter:
    """每个实例绑定运行时连接；等待首 token 时 Task.cancel 可直接打断。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        provider: str = "openai",
        timeout_s: float = 60.0,
        full_url: bool = False,
    ):
        self._provider = provider
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=normalize_base_url(base_url, "openai_chat", full_url=full_url) if base_url else None,
            timeout=timeout_s,
            max_retries=0,
            **(full_url_client_options(base_url, asynchronous=True) if full_url and base_url else {}),
        )

    async def close(self) -> None:
        """由应用资源拥有者关闭连接池。"""
        await close_async(self._client)

    async def stream(self, request: LlmRequest) -> AsyncIterator[StreamChunk]:
        """一次 SDK 请求对应一次 Attempt，EOF 不补发 Done。"""
        provider = request.provider or self._provider
        kwargs = request_options(request, provider, "openai_chat")
        kwargs.update(
            model=request.model,
            messages=to_openai_messages(
                request.messages,
                request.system,
                include_reasoning_content=is_newapi_template(request.reasoning_template_id) or provider in {"deepseek", "moonshot", "zhipu", "minimax"},
                request=request,
            ),
            stream=True,
            stream_options={"include_usage": True},
        )
        if request.tools:
            kwargs["tools"] = to_openai_tools(request.tools)
        stream = None
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            calls: dict[int, tuple[str, str]] = {}
            details: dict[int, dict] = {}
            finish = None
            usage = {}
            async for event in stream:
                chunk = plain(event)
                if chunk.get("usage") is not None:
                    usage.update(usage_values(chunk["usage"]))
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                if len(choices) != 1 or choices[0].get("index", 0) != 0:
                    raise invalid("单次请求返回了多个候选")
                choice = choices[0]
                delta = choice.get("delta") or {}
                if finish is not None and any(
                    delta.get(key) for key in ("content", "reasoning_content", "reasoning_details", "tool_calls")
                ):
                    raise invalid("结束信号之后仍出现语义增量")
                # MiniMax 的 reasoning_details 是累计快照；原样保存结构并只投影新文本。
                detail_text = ""
                if provider == "minimax":
                    for detail in delta.get("reasoning_details") or []:
                        index = detail.get("index", 0)
                        if not isinstance(index, int) or not isinstance(detail.get("text", ""), str):
                            raise invalid("MiniMax 思考增量不合法")
                        previous = details.get(index, {}).get("text", "")
                        current = detail.get("text", "")
                        if previous and not current.startswith(previous):
                            raise invalid("MiniMax 累计思考内容发生回退")
                        detail_text += current[len(previous):]
                        details[index] = {**details.get(index, {}), **detail}
                if detail_text and not delta.get("reasoning_content"):
                    yield ReasoningDelta(detail_text)
                if delta.get("reasoning_content"):
                    yield ReasoningDelta(delta["reasoning_content"])
                if delta.get("content"):
                    yield TextDelta(delta["content"])
                for call in delta.get("tool_calls") or []:
                    index = call["index"]
                    previous_id, previous_name = calls.get(index, ("", ""))
                    function = call.get("function") or {}
                    call_id, name = (
                        call.get("id") or previous_id,
                        function.get("name") or previous_name,
                    )
                    if (previous_id and previous_id != call_id) or (
                        previous_name and previous_name != name
                    ):
                        raise invalid("流式工具身份发生变化")
                    if (call_id, name) != (previous_id, previous_name):
                        calls[index] = call_id, name
                        yield ToolCallStart(index, call_id, name)
                    if function.get("arguments"):
                        yield ToolCallDelta(index, function["arguments"])
                if choice.get("finish_reason"):
                    if finish is not None:
                        raise invalid("重复结束信号")
                    finish = choice["finish_reason"]
            if finish is not None:
                state = None
                if details:
                    item = {"type": "minimax_reasoning", "details": list(details.values())}
                    yield ProviderItemStart("minimax-reasoning", 0, "minimax_reasoning")
                    yield ProviderItemEnd("minimax-reasoning", item)
                    state = make_state(request, provider, "openai_chat", [item])
                yield Done(normalize_openai_finish_reason(finish), usage, state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from None
        finally:
            if stream is not None:
                await close_async(stream)
