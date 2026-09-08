"""Responses 异步事件映射；无服务端会话依赖，原始 item 随事实回传。"""

import asyncio
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import openai

from ..loop_contracts import (
    Done,
    LlmRequest,
    ProviderItemDelta,
    ProviderItemEnd,
    ProviderItemStart,
    ReasoningDelta,
    StreamChunk,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    classify_provider_error,
)
from .common import (
    call_arguments,
    close_async,
    content_parts,
    invalid,
    make_state,
    normalize_base_url,
    plain,
    replay_items,
    usage_values,
    validate_messages,
)
from .options import request_options


def _validate_item(item: dict) -> None:
    """本地持有历史必须包含完整回传材料，不能只引用服务端临时状态。"""
    if not item.get("id") or item.get("status") in {"in_progress", "incomplete"}:
        raise invalid("Responses item 未完成或缺少身份")
    kind = item.get("type")
    if kind == "function_call":
        if (
            not item.get("call_id")
            or not item.get("name")
            or not isinstance(item.get("arguments"), str)
        ):
            raise invalid("Responses 工具 item 不完整")
    elif kind == "reasoning":
        if not item.get("encrypted_content") or not isinstance(item.get("summary"), list):
            raise invalid("Responses reasoning 缺少无状态回传材料")
    elif kind == "message":
        if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
            raise invalid("Responses message 结构不合法")
        if any(part.get("type") not in {"output_text", "refusal"} for part in item["content"]):
            raise invalid("Responses 返回未支持的消息内容")
    else:
        raise invalid("当前循环未支持此 Responses item")


def to_responses_input(request: LlmRequest, provider: str = "openai") -> list[dict[str, Any]]:
    """规范消息与原始块只选一个 assistant 来源，工具输出按 call_id 配对。"""
    validate_messages(request.messages)
    wire = []
    for message in request.messages:
        role = message["role"]
        if role == "tool":
            wire.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": content_parts(message["content"], "openai_responses"),
                }
            )
            continue
        items = replay_items(message, request, provider, "openai_responses")
        if items is not None:
            if role != "assistant":
                raise invalid("协议状态只能归属 assistant")
            for item in items:
                _validate_item(item)
            raw_calls = [
                (item["call_id"], item["name"], item["arguments"])
                for item in items
                if item["type"] == "function_call"
            ]
            if raw_calls != [
                (call["id"], call["name"], call_arguments(call))
                for call in message.get("tool_calls", [])
            ]:
                raise invalid("Responses 历史调用与协议块不一致")
            wire.extend(items)
            continue
        content = message.get("content", "")
        if content or not message.get("tool_calls"):
            wire.append(
                {"role": role, "content": content_parts(content, "openai_responses", role=role)}
            )
        if role == "assistant":
            wire.extend(
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["name"],
                    "arguments": call_arguments(call),
                }
                for call in message.get("tool_calls", [])
            )
    return wire


class ResponsesAdapter:
    """Responses 与 Chat 共用 SDK 但不共用消息/完成事件转换。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        provider: str = "openai",
        timeout_s: float = 60.0,
    ):
        self._provider = provider
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=normalize_base_url(base_url, "openai_responses") if base_url else None,
            timeout=timeout_s,
            max_retries=0,
        )

    async def close(self) -> None:
        """关闭实例连接池。"""
        await close_async(self._client)

    async def stream(self, request: LlmRequest) -> AsyncIterator[StreamChunk]:
        """只在真实 response 终态后发 Done，状态快照必须与 item 流一致。"""
        provider = request.provider or self._provider
        kwargs = request_options(request, provider, "openai_responses")
        kwargs.update(
            model=request.model,
            input=to_responses_input(request, provider),
            stream=True,
            store=False,
            include=["reasoning.encrypted_content"],
        )
        if request.system:
            kwargs["instructions"] = request.system
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                }
                for spec in request.tools
            ]
        stream = None
        try:
            stream = await self._client.responses.create(**kwargs)
            active, completed, arguments, text_parts, reasoning_parts = {}, {}, {}, {}, {}
            terminal = None
            async for sdk_event in stream:
                event = plain(sdk_event)
                kind = event["type"]
                if terminal is not None:
                    raise invalid("Responses 终态之后仍有事件")
                if kind == "response.output_item.added":
                    index, item = event["output_index"], event["item"]
                    if index in active or index in completed or not item.get("id"):
                        raise invalid("Responses item 身份缺失或重复")
                    if any(
                        previous["id"] == item["id"]
                        for previous in [*active.values(), *completed.values()]
                    ):
                        raise invalid("Responses item ID 重复")
                    active[index] = item
                    yield ProviderItemStart(item["id"], index, item["type"])
                    if item["type"] == "function_call":
                        yield ToolCallStart(index, item.get("call_id", ""), item.get("name", ""))
                        if item.get("arguments"):
                            arguments[index] = item["arguments"]
                            yield ToolCallDelta(index, item["arguments"])
                elif kind in {
                    "response.output_text.delta",
                    "response.refusal.delta",
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                    "response.function_call_arguments.delta",
                }:
                    index = event["output_index"]
                    if index not in active or active[index]["id"] != event["item_id"]:
                        raise invalid("Responses 增量引用未知 item")
                    fragment = event["delta"]
                    field = (
                        "arguments"
                        if kind == "response.function_call_arguments.delta"
                        else kind.removeprefix("response.").removesuffix(".delta")
                    )
                    expected = (
                        "function_call"
                        if field == "arguments"
                        else ("message" if field in {"output_text", "refusal"} else "reasoning")
                    )
                    if active[index]["type"] != expected:
                        raise invalid("Responses 增量与 item 类型不一致")
                    yield ProviderItemDelta(event["item_id"], field, fragment)
                    if field == "arguments":
                        if active[index]["type"] != "function_call":
                            raise invalid("Responses 参数增量指向非工具 item")
                        arguments[index] = arguments.get(index, "") + fragment
                        yield ToolCallDelta(index, fragment)
                    elif field in {"output_text", "refusal"}:
                        key = (index, event.get("content_index", 0), field)
                        text_parts[key] = text_parts.get(key, "") + fragment
                        yield TextDelta(fragment)
                    else:
                        position = event.get(
                            "summary_index"
                            if field == "reasoning_summary_text"
                            else "content_index",
                            0,
                        )
                        key = (index, position, field)
                        reasoning_parts[key] = reasoning_parts.get(key, "") + fragment
                        yield ReasoningDelta(fragment)
                elif kind == "response.function_call_arguments.done":
                    index = event["output_index"]
                    if index not in active or active[index]["id"] != event["item_id"]:
                        raise invalid("Responses 参数完成引用错误")
                    if index in arguments and arguments[index] != event["arguments"]:
                        raise invalid("Responses 参数片段与完成快照不一致")
                elif kind == "response.output_item.done":
                    index, item = event["output_index"], event["item"]
                    previous = active.get(index)
                    if (
                        previous is None
                        or previous["id"] != item.get("id")
                        or previous["type"] != item.get("type")
                    ):
                        raise invalid("Responses 完成 item 引用错误")
                    if item.get("status") == "incomplete":
                        # 截断项仅保留诊断增量，不能成为下一轮可回传状态。
                        continue
                    _validate_item(item)
                    if item["type"] == "function_call":
                        if (previous.get("call_id"), previous.get("name")) != (
                            item["call_id"],
                            item["name"],
                        ):
                            raise invalid("Responses 工具身份发生变化")
                        if index in arguments and arguments[index] != item["arguments"]:
                            raise invalid("Responses 工具参数快照不一致")
                        if index not in arguments:
                            yield ToolCallDelta(index, item["arguments"])
                    elif item["type"] == "message":
                        for part_index, part in enumerate(item["content"]):
                            field = "refusal" if part["type"] == "refusal" else "output_text"
                            value = part.get("refusal" if field == "refusal" else "text", "")
                            observed = text_parts.get((index, part_index, field))
                            if observed is not None and observed != value:
                                raise invalid("Responses 正文片段与快照不一致")
                            if observed is None and value:
                                yield TextDelta(value)
                        observed_count = [key for key in text_parts if key[0] == index]
                        if any(key[1] >= len(item["content"]) for key in observed_count):
                            raise invalid("Responses 完成快照缺少已输出正文")
                    elif item["type"] == "reasoning":
                        for field, parts in (
                            ("reasoning_summary_text", item["summary"]),
                            ("reasoning_text", item.get("content", [])),
                        ):
                            for position, part in enumerate(parts):
                                value = part.get("text", "")
                                observed = reasoning_parts.get((index, position, field))
                                if observed is not None and observed != value:
                                    raise invalid("Responses 思考增量与快照不一致")
                                if observed is None and value:
                                    yield ReasoningDelta(value)
                            if any(
                                key[0] == index and key[2] == field and key[1] >= len(parts)
                                for key in reasoning_parts
                            ):
                                raise invalid("Responses 快照缺少已输出思考")
                    active.pop(index)
                    completed[index] = deepcopy(item)
                    yield ProviderItemEnd(item["id"], deepcopy(item))
                elif kind in {"response.completed", "response.incomplete", "response.failed"}:
                    response = event["response"]
                    if response.get("status") not in (None, kind.removeprefix("response.")):
                        raise invalid("Responses 终态类型与快照状态不一致")
                    usage = usage_values(response.get("usage"))
                    if kind == "response.completed":
                        items = [completed[i] for i in sorted(completed)]
                        if active or items != response.get("output", []):
                            raise invalid("Responses 终态与已闭合 item 流不一致")
                        state = make_state(request, provider, "openai_responses", items)
                        reason = (
                            "tool_calls"
                            if any(item["type"] == "function_call" for item in items)
                            else "stop"
                        )
                        terminal = Done(reason, usage, state)
                    elif kind == "response.incomplete":
                        reason = (response.get("incomplete_details") or {}).get(
                            "reason", "incomplete"
                        )
                        terminal = Done(
                            "max_tokens" if reason == "max_output_tokens" else f"error:{reason}",
                            usage,
                        )
                    else:
                        terminal = Done("error:failed", usage)
                elif kind == "error":
                    raise invalid("Responses 返回流错误")
            if terminal is not None:
                yield terminal
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from None
        finally:
            if stream is not None:
                await close_async(stream)
