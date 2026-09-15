"""Anthropic 异步 Messages；完整保留工具、thinking 签名与缓存用量。"""

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import anthropic

from ..loop_contracts import (
    Done,
    LlmRequest,
    Message,
    ProviderItemDelta,
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
    anthropic_usage,
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


def _allows_unsigned_thinking(request: LlmRequest | None) -> bool:
    """兼容供应商的 Messages 流可省略签名，原生 Claude 仍严格要求签名。"""
    return request is not None and request.provider in {
        "deepseek", "qwen", "zhipu", "moonshot", "minimax", "volcengine",
    }


def _validate_block(block: dict, *, allow_unsigned_thinking: bool = False) -> None:
    """只允许已实现且可完整回传的内容类型，不把隐藏块降成普通文本。"""
    kind = block.get("type")
    if kind == "thinking":
        if (
            not isinstance(block.get("thinking"), str)
            or not isinstance(block.get("signature", ""), str)
            or (not allow_unsigned_thinking and not block.get("signature"))
        ):
            raise invalid("thinking 块缺少必要签名")
    elif kind == "redacted_thinking":
        if not block.get("data"):
            raise invalid("隐藏思考块缺少回传数据")
    elif kind == "tool_use":
        if not block.get("id") or not block.get("name") or not isinstance(block.get("input"), dict):
            raise invalid("tool_use 块不完整")
    elif kind == "text":
        if not isinstance(block.get("text"), str):
            raise invalid("文本块不完整")
    else:
        raise invalid("当前循环未支持此 Anthropic 内容块")


def to_anthropic_messages(
    messages: list[Message], *, request: LlmRequest | None = None, provider: str = "anthropic"
) -> list[dict[str, Any]]:
    """连续结果合并为同一 user 消息；有协议状态时只回传一份原始 assistant。"""
    validate_messages(messages)
    if request is None and any(message.get("protocol_state") is not None for message in messages):
        raise invalid("回传协议状态必须提供用于兼容性校验的请求")
    wire = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": content_parts(message["content"], "anthropic_messages"),
            }
            if message.get("is_error"):
                block["is_error"] = True
            if (
                wire
                and wire[-1]["role"] == "user"
                and isinstance(wire[-1]["content"], list)
                and wire[-1]["content"]
                and wire[-1]["content"][0].get("type") == "tool_result"
            ):
                wire[-1]["content"].append(block)
            else:
                wire.append({"role": "user", "content": [block]})
        elif role == "assistant":
            blocks = (
                replay_items(message, request, provider, "anthropic_messages") if request else None
            )
            if blocks is not None:
                for block in blocks:
                    _validate_block(block, allow_unsigned_thinking=_allows_unsigned_thinking(request))
                raw_calls = [
                    (block["id"], block["name"]) for block in blocks if block["type"] == "tool_use"
                ]
                if raw_calls != [
                    (call["id"], call["name"]) for call in message.get("tool_calls", [])
                ]:
                    raise invalid("历史工具身份与协议块不一致")
                raw_tools = [block for block in blocks if block["type"] == "tool_use"]
                for block, call in zip(raw_tools, message.get("tool_calls", []), strict=True):
                    if isinstance(call.get("args"), dict) and block["input"] != call["args"]:
                        raise invalid("历史工具参数与协议块不一致")
            else:
                content = content_parts(message.get("content", ""), "anthropic_messages", role=role)
                blocks = (
                    [{"type": "text", "text": content}]
                    if isinstance(content, str) and content
                    else (content if isinstance(content, list) else [])
                )
                for call in message.get("tool_calls", []):
                    # 保留源已结算坏参数的修复语义；不可将这个对象作为执行参数。
                    args = call.get("args")
                    if not isinstance(args, dict) and not call.get("parse_error"):
                        raise invalid("历史工具调用缺少已解析参数或错误标记")
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call["id"],
                            "name": call["name"],
                            "input": args if isinstance(args, dict) else {},
                        }
                    )
            wire.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif role == "user":
            wire.append(
                {
                    "role": "user",
                    "content": content_parts(message.get("content", ""), "anthropic_messages"),
                }
            )
        else:
            raise invalid("Anthropic system 必须通过顶层字段传入")
    return wire


def to_anthropic_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """源 parameters 对应 Anthropic input_schema。"""
    return [
        {"name": spec.name, "description": spec.description, "input_schema": spec.parameters}
        for spec in specs
    ]


def normalize_anthropic_finish_reason(reason: str) -> str:
    """保留源停止及预算终态。"""
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "max_tokens",
    }.get(reason, f"error:{reason}")


class AnthropicAdapter:
    """SDK 只执行一次请求；缓存、签名与取消不依赖全局配置。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        provider: str = "anthropic",
        timeout_s: float = 60.0,
        full_url: bool = False,
    ):
        self._provider = provider
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=normalize_base_url(base_url, "anthropic_messages", full_url=full_url) if base_url else None,
            timeout=timeout_s,
            max_retries=0,
            **(full_url_client_options(base_url, asynchronous=True) if full_url and base_url else {}),
        )

    async def close(self) -> None:
        """关闭本实例连接池。"""
        await close_async(self._client)

    async def stream(self, request: LlmRequest) -> AsyncIterator[StreamChunk]:
        """语义增量与内部块同源；只有已闭合状态进入 Done。"""
        provider = request.provider or self._provider
        kwargs = request_options(request, provider, "anthropic_messages")
        kwargs.update(
            model=request.model,
            messages=to_anthropic_messages(
                request.messages,
                request=request,
                provider=provider,
            ),
            stream=True,
        )
        if request.system:
            kwargs["system"] = request.system
        if request.system_segments and request.provider_options.get("prompt_cache"):
            segments = request.system_segments
            last = max(
                (i for i, segment in enumerate(segments) if segment.cacheable and segment.text),
                default=-1,
            )
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": segment.text,
                    **({"cache_control": {"type": "ephemeral"}} if i == last else {}),
                }
                for i, segment in enumerate(segments)
                if segment.text
            ]
        if request.tools:
            kwargs["tools"] = to_anthropic_tools(request.tools)
        stream = None
        try:
            stream = await self._client.messages.create(**kwargs)
            blocks, completed, arguments = {}, {}, {}
            usage, finish, message_id = {}, None, "message"
            async for sdk_event in stream:
                event = plain(sdk_event)
                kind = event["type"]
                if kind == "message_start":
                    message = event["message"]
                    message_id = message.get("id", "message")
                    usage.update(usage_values(message.get("usage")))
                elif kind == "content_block_start":
                    index, block = event["index"], event["content_block"]
                    if index in blocks or index in completed or finish:
                        raise invalid("重复或迟到的内容块")
                    blocks[index] = deepcopy(block)
                    yield ProviderItemStart(f"{message_id}:{index}", index, block["type"])
                    if block["type"] == "tool_use":
                        yield ToolCallStart(index, block.get("id", ""), block.get("name", ""))
                    elif block["type"] == "text" and block.get("text"):
                        yield TextDelta(block["text"])
                    elif block["type"] == "thinking" and block.get("thinking"):
                        yield ReasoningDelta(block["thinking"])
                elif kind == "content_block_delta":
                    index, delta = event["index"], event["delta"]
                    if index not in blocks or finish:
                        raise invalid("增量没有活动内容块")
                    field = {
                        "text_delta": "text",
                        "thinking_delta": "thinking",
                        "signature_delta": "signature",
                        "input_json_delta": "partial_json",
                    }.get(delta["type"])
                    if field is None:
                        raise invalid("未实现的内容增量")
                    fragment = delta[field]
                    expected = {
                        "text": "text",
                        "thinking": "thinking",
                        "signature": "thinking",
                        "partial_json": "tool_use",
                    }[field]
                    if blocks[index]["type"] != expected:
                        raise invalid("内容增量与块类型不一致")
                    yield ProviderItemDelta(
                        f"{message_id}:{index}",
                        "arguments_raw" if field == "partial_json" else field,
                        fragment,
                    )
                    if field == "partial_json":
                        if blocks[index]["type"] != "tool_use":
                            raise invalid("工具参数增量指向非工具块")
                        arguments[index] = arguments.get(index, "") + fragment
                        yield ToolCallDelta(index, fragment)
                    else:
                        blocks[index][field] = blocks[index].get(field, "") + fragment
                        if field == "text":
                            yield TextDelta(fragment)
                        elif field == "thinking":
                            yield ReasoningDelta(fragment)
                elif kind == "content_block_stop":
                    index = event["index"]
                    if index not in blocks:
                        raise invalid("内容块重复关闭")
                    block = blocks.pop(index)
                    if block["type"] == "tool_use":
                        if index in arguments:
                            try:
                                parsed = json.loads(arguments[index])
                                block["input"] = parsed if isinstance(parsed, dict) else {}
                            except ValueError:
                                # 原串已交给 Attempt；这里只修复 Anthropic 下一轮所需对象形状。
                                block["input"] = {}
                        else:
                            yield ToolCallDelta(
                                index, json.dumps(block.get("input", {}), ensure_ascii=False)
                            )
                    _validate_block(block, allow_unsigned_thinking=_allows_unsigned_thinking(request))
                    completed[index] = block
                    yield ProviderItemEnd(f"{message_id}:{index}", deepcopy(block))
                elif kind == "message_delta":
                    reason = event.get("delta", {}).get("stop_reason")
                    if reason:
                        if finish is not None:
                            raise invalid("重复消息结束信号")
                        finish = reason
                    usage.update(usage_values(event.get("usage")))
                elif kind == "error":
                    raise invalid("供应商返回流错误")
            if finish is not None:
                if blocks and finish not in {"max_tokens"}:
                    raise invalid("消息结束但内容块未闭合")
                state = (
                    make_state(
                        request,
                        provider,
                        "anthropic_messages",
                        [completed[i] for i in sorted(completed)],
                    )
                    if not blocks
                    else None
                )
                yield Done(normalize_anthropic_finish_reason(finish), anthropic_usage(usage), state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from None
        finally:
            if stream is not None:
                await close_async(stream)
