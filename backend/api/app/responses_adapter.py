"""旧 ModelGateway 的 Responses 同步桥接，保持既有错误和取消契约。"""

import time

import openai
from shared.reasoning import openai_effort
from shared.responses import ResponsesStream, response_body, response_text, response_usage

from .errors import AppError, ErrorCode


def _body(*, model, messages, system, temperature, max_tokens, reasoning_enabled, reasoning_effort, tools):
    """复用公共消息转换，仅为显式开启的请求添加 reasoning 参数。"""
    from .adapters import _adapt_tools

    body = response_body(model=model, messages=messages, system=system,
                         temperature=temperature, max_tokens=max_tokens)
    name = model.strip().lower().rsplit("/", 1)[-1]
    # 关闭旧推理模型时不发送不受支持的 none；固定思考能力由协议档探测约束。
    effort = openai_effort(model, reasoning_effort) if reasoning_enabled else (
        "none" if name.startswith(("gpt-5.1", "gpt-5.2", "gpt-5.3", "gpt-5.4")) else None
    )
    if effort and not ("[" in model and model.rstrip().endswith("]")):
        body["reasoning"] = {"effort": effort}
        if reasoning_enabled:
            body["reasoning"]["summary"] = "auto"
        body.pop("temperature", None)
    if tools:
        body["tools"] = [{"type": "function", **item["function"], "strict": False}
                         for item in _adapt_tools(tools, "openai_chat")]
    return body


def _client(base_url, api_key, timeout_s, full_url):
    """沿用统一 URL 规则及完整 URL hook。"""
    from .llm.providers.common import full_url_client_options, normalize_base_url

    return openai.OpenAI(
        api_key=api_key, timeout=timeout_s, max_retries=0,
        base_url=normalize_base_url(base_url, "openai_responses", full_url=full_url),
        **(full_url_client_options(base_url) if full_url else {}),
    )


def _calls(data):
    """仅完成快照中的函数调用进入旧工具链。"""
    from .adapters import _complete_stream_tool_call

    calls = []
    for item in data["output"]:
        if item.get("type") == "function_call":
            if not item.get("call_id") or not item.get("name"):
                raise ValueError("Responses 工具身份缺失")
            call = _complete_stream_tool_call(item.get("call_id"), item.get("name"), item.get("arguments"))
            if call is not None:
                calls.append(call)
    return tuple(calls)


def _error(exc):
    """上游原文和凭据绝不进入可展示的错误信息。"""
    if isinstance(exc, openai.APITimeoutError | TimeoutError):
        return AppError(ErrorCode.TIMEOUT, "上游调用超时")
    return AppError(ErrorCode.UPSTREAM, "Responses 上游调用失败或响应不完整")


def call_responses(*, base_url, api_key, timeout_s, full_url=False, **kwargs):
    """执行一次非流式请求并拒绝失败、截断和损坏响应。"""
    from .adapters import AdapterResult, _close_quietly, _sdk_response_dict

    started = time.perf_counter()
    client = None
    try:
        body = _body(**kwargs)
        client = _client(base_url, api_key, timeout_s, full_url)
        data = _sdk_response_dict(client.responses.create(**body))
        return AdapterResult(text=response_text(data), usage=response_usage(data), raw=data,
                             latency_ms=round((time.perf_counter() - started) * 1000), tool_calls=_calls(data))
    except (openai.APIError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise _error(exc) from exc
    finally:
        if client is not None:
            _close_quietly(client)


def stream_responses(*, base_url, api_key, timeout_s, full_url=False, should_abort=None, **kwargs):
    """同步 SSE 桥接；只有成功终态才交付工具，取消和 EOF 不执行半截参数。"""
    from .adapters import (
        AdapterStreamEvent,
        StreamAborted,
        _close_quietly,
        _ensure_sse_stream,
        _sdk_response_dict,
    )

    client = stream = None
    deadline = time.monotonic() + timeout_s
    decoder = ResponsesStream()
    try:
        if should_abort and should_abort():
            raise StreamAborted()
        body = _body(**kwargs)
        client = _client(base_url, api_key, timeout_s, full_url)
        stream = client.responses.create(**body, stream=True)
        _ensure_sse_stream(stream)
        for event in stream:
            if should_abort and should_abort():
                raise StreamAborted()
            if time.monotonic() > deadline:
                raise TimeoutError()
            for part in decoder.feed(_sdk_response_dict(event)):
                if part[0] in {"text", "reasoning"}:
                    yield ("content" if part[0] == "text" else "reasoning", part[1])
        if decoder.response is None:
            raise ValueError("Responses 缺少完成事件")
        response_text(decoder.response)
        for call in _calls(decoder.response):
            yield AdapterStreamEvent(kind="tool_call", tool_call=call)
    except (openai.APIError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise _error(exc) from exc
    finally:
        if stream is not None:
            _close_quietly(stream)
        if client is not None:
            _close_quietly(client)
