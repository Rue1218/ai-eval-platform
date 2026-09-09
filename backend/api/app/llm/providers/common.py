"""两类协议共享的纯转换与资源关闭，不引入图、数据库或应用配置。"""

import inspect
import json
from copy import deepcopy
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..loop_contracts import LlmRequest, LlmRequestError, ProtocolState, header_fingerprint


def invalid(message: str = "模型流结构不完整") -> LlmRequestError:
    """结构损坏不可自动重试，也不能伪造完成状态。"""
    return LlmRequestError(message, code="provider_protocol")


async def close_async(resource: Any) -> None:
    """兼容 SDK 的异步及测试替身的同步关闭接口。"""
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close is not None:
        result = close()
        if inspect.isawaitable(result):
            await result


def plain(value: Any) -> Any:
    """SDK 对象转可持久化 JSON，去除未提供的可选字段。"""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return deepcopy(value)


def normalize_base_url(base_url: str, protocol: str) -> str:
    """剥离资源后缀后只补一次版本段；带凭据的地址拒绝进入配置。"""
    parts = urlsplit(base_url.strip())
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise LlmRequestError("模型服务地址不合法", code="model_config")
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/messages", "/models"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if protocol == "anthropic_messages":
        if path.endswith("/v1"):
            path = path[:-3]
    elif not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def compatibility_key(provider: str, protocol: str, model: str) -> str:
    """协议与模型必须完全一致才默认允许回传不透明块。"""
    return header_fingerprint({"provider": provider, "protocol": protocol, "model": model})


def make_state(request: LlmRequest, provider: str, protocol: str, items: list) -> ProtocolState:
    """完成态限制大小并复制，避免后续增量修改已发出的快照。"""
    if len(json.dumps(items, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
        raise invalid("模型协议状态超过大小上限")
    return ProtocolState(
        provider=provider,
        protocol=protocol,
        model=request.model,
        compatibility_key=request.compatibility_key
        or compatibility_key(provider, protocol, request.model),
        items=deepcopy(items),
    )


def replay_items(message: dict, request: LlmRequest, provider: str, protocol: str) -> list | None:
    """显式校验落库状态的兼容边界，不能静默删除其他模型签名。"""
    state = message.get("protocol_state")
    if state is None:
        return None
    if isinstance(state, ProtocolState):
        state = asdict(state)
    key = request.compatibility_key or compatibility_key(provider, protocol, request.model)
    if not isinstance(state, dict) or any(
        (
            state.get("version") != 1,
            state.get("replay_policy") != "items_v1",
            state.get("provider") != provider,
            state.get("protocol") != protocol,
            state.get("model") != request.model,
            state.get("compatibility_key") != key,
        )
    ):
        raise LlmRequestError("历史协议状态与当前模型不兼容", code="protocol_state_incompatible")
    items = state.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise invalid("历史协议状态结构不合法")
    return make_state(request, provider, protocol, items).items


def content_parts(content: Any, protocol: str, *, role: str = "user") -> Any:
    """严格转换平台 text/image_url，拒绝静默丢附件或未知内容块。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise invalid("消息内容必须为文本或图文块")
    result = []
    for part in content:
        if not isinstance(part, dict):
            raise invalid("图文块结构不合法")
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            result.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            image = part.get("image_url", {})
            url = image.get("url") if isinstance(image, dict) else None
            if not isinstance(url, str) or not url:
                raise invalid("图片引用为空")
            if protocol == "anthropic_messages":
                if url.startswith("data:"):
                    header, sep, data = url.partition(",")
                    if not sep or ";base64" not in header or not data:
                        raise invalid("图片数据编码不合法")
                    source = {
                        "type": "base64",
                        "media_type": header[5:].split(";")[0],
                        "data": data,
                    }
                else:
                    source = {"type": "url", "url": url}
                result.append({"type": "image", "source": source})
            else:
                result.append({"type": "image_url", "image_url": deepcopy(image)})
        else:
            raise invalid("不支持的消息内容块")
    return result


def call_arguments(call: dict) -> str:
    """优先回传原始参数；不在适配器中解析坏 JSON 或改写为可执行对象。"""
    if not call.get("id") or not call.get("name"):
        raise invalid("历史工具调用身份缺失")
    if isinstance(call.get("arguments_raw"), str):
        return call["arguments_raw"]
    if not isinstance(call.get("args"), dict):
        raise invalid("历史工具调用缺少参数")
    return json.dumps(call["args"], ensure_ascii=False)


def validate_messages(messages: list[dict]) -> None:
    """模型请求只能包含完整消息组；未知角色和错位调用不得被 codec 静默删掉。"""
    pending: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {
            "user",
            "assistant",
            "tool",
        }:
            raise invalid("未知的规范消息角色")
        role = message["role"]
        if role != "assistant" and (
            message.get("tool_calls") or message.get("protocol_state") is not None
        ):
            raise invalid("调用和协议状态只能归属助手消息")
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                raise invalid("工具结果缺少配对调用")
            name = pending.pop(call_id)
            if message.get("name", name) != name:
                raise invalid("工具结果名称与调用不一致")
        else:
            if pending:
                raise invalid("未完成工具组中插入了新消息")
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise invalid("工具调用必须是列表")
            for call in calls:
                if not isinstance(call, dict):
                    raise invalid("工具调用必须是对象")
                call_arguments(call)
                call_id, name = call["id"], call["name"]
                if not isinstance(call_id, str) or not isinstance(name, str) or call_id in pending:
                    raise invalid("工具调用身份无效或重复")
                pending[call_id] = name
    if pending:
        raise invalid("模型请求缺少工具结果")


def usage_values(value: Any) -> dict[str, int]:
    """保留实际用量和缓存/推理明细；缺失字段不伪造为零。"""
    raw = plain(value) or {}
    result = {
        key: count
        for key, count in raw.items()
        if isinstance(count, int) and not isinstance(count, bool)
    }
    for old, new in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("cache_read_input_tokens", "cached_tokens"),
    ):
        if old in result:
            result[new] = result[old]
    for key in (
        "prompt_tokens_details",
        "input_tokens_details",
        "completion_tokens_details",
        "output_tokens_details",
    ):
        for name, count in (raw.get(key) or {}).items():
            if isinstance(count, int):
                result[name] = count
    return result


def anthropic_usage(values: dict[str, int]) -> dict[str, int]:
    """保留原始分项，规范输入为未缓存输入加缓存读写；明细不二次加入总量。"""
    result = dict(values)
    if "input_tokens" in result:
        result["prompt_tokens"] = sum(
            result[key]
            for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            if key in result
        )
    if "prompt_tokens" in result and "completion_tokens" in result:
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    return result


def validate_request(request: LlmRequest, protocol: str) -> None:
    """新字段不可覆盖协议身份；思考冲突在网络请求前拒绝。"""
    if request.protocol not in (None, protocol):
        raise invalid("请求协议与适配器不一致")
    if request.system_segments:
        if request.system != "\n\n".join(segment.text for segment in request.system_segments):
            raise LlmRequestError("system 与分段正文不一致", code="model_config")
        dynamic = False
        for segment in request.system_segments:
            if dynamic and segment.cacheable:
                raise LlmRequestError("缓存段必须位于动态段之前", code="model_config")
            dynamic |= not segment.cacheable
    enabled = request.reasoning_enabled
    if enabled is not None and request.thinking is not None and enabled != request.thinking:
        raise LlmRequestError("思考配置冲突", code="model_config")
    if request.reasoning_effort is not None:
        expected = request.reasoning_effort != "off"
        if any(flag is not None and flag != expected for flag in (enabled, request.thinking)):
            raise LlmRequestError("思考档位与开关冲突", code="model_config")
    if request.max_tokens <= 0 or (request.timeout_s is not None and request.timeout_s <= 0):
        raise LlmRequestError("模型预算或超时不合法", code="model_config")
