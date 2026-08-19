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

        def extract(data: dict) -> str:
            # 兼容网关在 max_tokens=1 时可能返回 content=None
            choices = data["choices"]
            return str(choices[0]["message"].get("content") or "")

    elif protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body = {"model": model, "input": list(messages), "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        headers["Authorization"] = f"Bearer {api_key}"

        def extract(data: dict) -> str:
            # output 数组内仅拼接 output_text 内容块
            return "".join(
                str(part.get("text") or "")
                for item in data["output"]
                for part in (item.get("content") or [])
                if part.get("type") == "output_text"
            )

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

        def extract(data: dict) -> str:
            # content 数组内仅拼接 text 内容块
            return "".join(
                str(block.get("text") or "") for block in data["content"] if block.get("type") == "text"
            )

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
        text = extract(data)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常") from exc

    return AdapterResult(
        text=text,
        usage=_norm_usage(data, anthropic=protocol == "anthropic_messages"),
        raw=data,
        latency_ms=latency_ms,
    )
