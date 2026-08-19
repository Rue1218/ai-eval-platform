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
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import AppError, ErrorCode

# 契约支持的三种协议（与 protocol_profiles 的 CHECK 约束一致）
SUPPORTED_PROTOCOLS = ("openai_chat", "openai_responses", "anthropic_messages")

# 非流式调用被测 / Agent 模型的默认超时秒数
DEFAULT_TIMEOUT_S = 30.0


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


def _post_json(url: str, body: dict, headers: dict, timeout_s: float) -> dict:
    """同步 POST JSON 并解析上游响应对象。

    独立成函数便于夹具单测：测试通过 monkeypatch 替换本函数即可
    注入成功 payload、4xx 异常或超时，不依赖真实上游。
    """
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode())


def _norm_usage(data: dict, *, anthropic: bool) -> dict:
    """把三协议各自的 usage 字段归一为统一 token 计数结构。"""
    usage = data.get("usage") or {}
    if anthropic:
        # Anthropic 使用 input_tokens / output_tokens 命名，total 需自行求和
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


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


def call_protocol(
    *,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    anthropic_version: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> AdapterResult:
    """按协议适配调用上游模型并返回统一结构的结果对象。

    ``messages`` 为 ``[{"role": "user" | "assistant", "content": "..."}]``；
    系统提示词经 ``system`` 独立传入，由各协议以自身字段承载
    （chat 的 system 消息 / responses 的 instructions / anthropic 的 system）。
    """
    if protocol not in SUPPORTED_PROTOCOLS:
        raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{protocol}")

    base = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}

    if protocol == "openai_chat":
        url = f"{base}/v1/chat/completions"
        chat: list[dict] = ([{"role": "system", "content": system}] if system else []) + list(messages)
        body: dict = {
            "model": model,
            "messages": chat,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # mimo-v2.5 系列是推理模型，默认先产出一大段 reasoning_content 再出正文，
        # 既拖慢响应（实测 18s→2s）又可能挤占 max_tokens 导致正文为空。
        # 该网关支持显式关闭思考；其它 OpenAI 兼容端点不动该字段以免被 400 拒绝。
        if "xiaomimimo" in base:
            body["thinking"] = {"type": "disabled"}
        headers["Authorization"] = f"Bearer {api_key}"

    elif protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body = {"model": model, "input": list(messages), "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        headers["Authorization"] = f"Bearer {api_key}"

    else:  # anthropic_messages
        url = f"{base}/v1/messages"
        body = {
            "model": model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = anthropic_version or "2023-06-01"

    started = time.perf_counter()
    try:
        data = _post_json(url, body, headers, timeout_s)
    except HTTPError as exc:
        # 仅回显状态码，绝不把请求头（含 Key）或上游原文带给浏览器
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc

    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        text = _full_text(protocol, data)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常") from exc

    return AdapterResult(
        text=text,
        usage=_norm_usage(data, anthropic=protocol == "anthropic_messages"),
        raw=data,
        latency_ms=latency_ms,
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
    max_tokens: int = 1024,
    anthropic_version: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Iterator[tuple[str, str]]:
    """按协议流式调用上游模型，逐块 yield ``(kind, text)`` 增量（SSE）。

    ``kind`` 为增量类别：``"content"`` 是正式回复正文，``"reasoning"``
    是推理模型的前置思考链（deepseek 风格 ``reasoning_content`` /
    anthropic ``thinking_delta`` / responses ``reasoning_summary``），
    供前端思考卡展示；上游未产生思考链时全程只 yield content。

    ``timeout_s`` 同时约束建连、单次读与整体流式时长，超时统一归一为
    TIMEOUT，上游 4xx/5xx 归一为 UPSTREAM。若网关忽略 ``stream``
    参数直接返回完整 JSON（非 SSE），则兜底解析全文并作为单块
    content yield，保证调用方拿到正确结果而非空流降级。
    """
    if protocol not in SUPPORTED_PROTOCOLS:
        raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{protocol}")

    base = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}

    if protocol == "openai_chat":
        url = f"{base}/v1/chat/completions"
        chat: list[dict] = ([{"role": "system", "content": system}] if system else []) + list(messages)
        body: dict = {
            "model": model,
            "messages": chat,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # 与 call_protocol 一致：mimo 网关显式关闭思考，正文直接流式输出
        if "xiaomimimo" in base:
            body["thinking"] = {"type": "disabled"}
        headers["Authorization"] = f"Bearer {api_key}"

        def delta_of(data: dict) -> tuple[str, str]:
            choices = data.get("choices") or [{}]
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                # 推理模型的思考链增量（deepseek/mimo 等风格）
                return ("reasoning", str(delta["reasoning_content"]))
            return ("content", str(delta.get("content") or ""))

    elif protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body = {"model": model, "input": list(messages), "stream": True, "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        headers["Authorization"] = f"Bearer {api_key}"

        def delta_of(data: dict) -> tuple[str, str]:  # noqa: F811  （各分支同名提取器，互斥定义）
            kind = data.get("type")
            if kind == "response.reasoning_summary_text.delta":
                return ("reasoning", str(data.get("delta") or ""))
            if kind == "response.output_text.delta":
                return ("content", str(data.get("delta") or ""))
            return ("content", "")

    else:  # anthropic_messages
        url = f"{base}/v1/messages"
        body = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = anthropic_version or "2023-06-01"

        def delta_of(data: dict) -> tuple[str, str]:  # noqa: F811
            if data.get("type") == "content_block_delta":
                delta = data.get("delta") or {}
                if delta.get("type") == "thinking_delta":
                    return ("reasoning", str(delta.get("thinking") or ""))
                if delta.get("type") == "text_delta":
                    return ("content", str(delta.get("text") or ""))
            return ("content", "")

    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    deadline = time.monotonic() + timeout_s
    try:
        response = urlopen(request, timeout=timeout_s)
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc

    # 非喂 SSE data 行的响应体（网关忽略 stream 参数时的完整 JSON）
    non_sse_lines: list[str] = []
    yielded = False
    try:
        with response:
            for raw_line in response:
                # 整体流式时长兜底：超时视为上游卡死，归一为 TIMEOUT
                if time.monotonic() > deadline:
                    raise TimeoutError("stream deadline exceeded")
                line = raw_line.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    # SSE 的 event:/注释行/空行跳过；但完整 JSON 响应需收集作兜底
                    if line:
                        non_sse_lines.append(line)
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue  # 容忍个别坏帧，不中断整条流
                if not isinstance(data, dict):
                    continue
                kind, text = delta_of(data)
                if text:
                    yielded = True
                    yield (kind, text)
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "上游调用超时") from exc
    except OSError as exc:
        # 读流中连接中断（对端重置等）：统一归一为 UPSTREAM
        raise AppError(ErrorCode.UPSTREAM, "上游连接中断") from exc

    # 兜底：SSE 流中无任何增量且响应体是完整 JSON —— 网关按非流式返回了结果，
    # 用非流式提取器解析全文作为单块 content，避免调用方拿到空流而错误降级。
    if not yielded and non_sse_lines:
        joined = "\n".join(non_sse_lines).strip()
        if joined.startswith("{"):
            try:
                data = json.loads(joined)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                try:
                    text = _full_text(protocol, data)
                except (KeyError, IndexError, TypeError, AttributeError):
                    text = ""
                if text:
                    # 网关忽略 stream 参数：记录一次便于排查上游流式支持情况
                    logging.getLogger(__name__).info(
                        "上游 %s 忽略 stream 参数返回完整 JSON，走非 SSE 兜底", base
                    )
                    yield ("content", text)


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
    """
    base = base_url.rstrip("/")
    clean_base = base[:-3] if base.endswith("/v1") else base

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        if protocol == "anthropic_messages":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = anthropic_version or "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    urls_to_try: list[str] = []
    if protocol == "anthropic_messages":
        urls_to_try = [f"{base}/v1/models", f"{clean_base}/v1/models"]
    else:
        urls_to_try = [
            f"{clean_base}/v1/models",
            f"{base}/models",
            f"{clean_base}/api/tags",
        ]

    last_error: Exception | None = None
    data: dict | None = None
    for url in urls_to_try:
        try:
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout_s) as response:
                data = json.loads(response.read().decode())
                if isinstance(data, dict):
                    break
        except HTTPError as exc:
            last_error = exc
            if exc.code in (401, 403):
                raise AppError(ErrorCode.UNAUTHORIZED, f"上游鉴权失败 ({exc.code})，请检查 API Key") from exc
            continue
        except Exception as exc:
            last_error = exc
            continue

    models_list: list[dict] = []
    if data and isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                if isinstance(item, dict) and item.get("id"):
                    models_list.append({
                        "id": str(item["id"]),
                        "name": str(item.get("id")),
                        "owned_by": str(item.get("owned_by") or item.get("root") or "remote"),
                    })
        elif "models" in data and isinstance(data["models"], list):
            for item in data["models"]:
                if isinstance(item, dict) and item.get("name"):
                    models_list.append({
                        "id": str(item["name"]),
                        "name": str(item.get("name")),
                        "owned_by": "ollama",
                    })

    if models_list:
        models_list.sort(key=lambda x: x["id"].lower())
        return models_list

    if protocol == "anthropic_messages":
        return [
            {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet", "owned_by": "anthropic"},
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet v2", "owned_by": "anthropic"},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "owned_by": "anthropic"},
            {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "owned_by": "anthropic"},
        ]

    if last_error:
        raise AppError(ErrorCode.UPSTREAM, f"无法从端点获取模型列表: {last_error}")
    raise AppError(ErrorCode.UPSTREAM, "端点未返回可解析的模型列表，请手动输入模型标识名")
