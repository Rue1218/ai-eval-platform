"""Worker 侧三协议统一调用器（镜像 ``api/app/adapters.py`` 的 ``call_protocol``）。

容器隔离导致 Worker 无法直接复用 api 包；本文件与其镜像源保持同一套
端点 / 鉴权头 / 响应解析逻辑，修改任一侧必须同步另一侧（技术债：后续
抽共享 package，见 ``worker/app/models.py`` 头注释）。

- ``openai_chat``        POST ``{base}/v1/chat/completions``   ``Authorization: Bearer``
- ``openai_responses``   POST ``{base}/v1/responses``          ``Authorization: Bearer``
- ``anthropic_messages`` POST ``{base}/v1/messages``           ``x-api-key`` + ``anthropic-version``

失败统一归一为 ``ProtocolCallError``：上游 4xx/5xx 与连接错误 → ``UPSTREAM``，
超时 → ``TIMEOUT``，参数问题 → ``VALIDATION``；异常信息绝不携带 API Key。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# 契约支持的三种协议（与 protocol_profiles 的 CHECK 约束一致）
SUPPORTED_PROTOCOLS = ("openai_chat", "openai_responses", "anthropic_messages")

# 非流式调用被测模型的默认超时秒数
DEFAULT_TIMEOUT_S = 30.0


class ProtocolCallError(Exception):
    """协议调用失败：code 取 UPSTREAM / TIMEOUT / VALIDATION 之一。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class AdapterResult:
    """三协议统一调用结果。

    ``usage`` 已归一为 ``prompt_tokens / completion_tokens / total_tokens``；
    ``raw`` 保留上游原始 JSON 对象，消费方落库时按契约截断到 32KB。
    """

    text: str
    usage: dict
    raw: dict
    latency_ms: int


def _post_json(url: str, body: dict, headers: dict, timeout_s: float) -> dict:
    """同步 POST JSON 并解析上游响应对象。"""
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode())


def _norm_usage(data: dict, *, anthropic: bool) -> dict:
    """把三协议各自的 usage 字段归一为统一 token 计数结构。"""
    usage = data.get("usage") or {}
    if anthropic:
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
    """从完整（非流式）响应对象中提取全文。"""
    if protocol == "openai_chat":
        choices = data["choices"]
        return str(choices[0]["message"].get("content") or "")
    if protocol == "openai_responses":
        return "".join(
            str(part.get("text") or "")
            for item in data["output"]
            for part in (item.get("content") or [])
            if part.get("type") == "output_text"
        )
    return "".join(str(block.get("text") or "") for block in data["content"] if block.get("type") == "text")


def _service_base_url(base_url: str) -> str:
    """规范化协议服务根地址，兼容带或不带 ``/v1`` 的协议档配置。

    Worker 与 API 侧调用器均会统一追加 ``/v1``。仅剥离输入地址末尾的
    版本段，避免真实评测请求生成 ``/v1/v1/...``，而不改写持久化配置。
    """
    base = base_url.strip().rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


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
    """按协议适配调用被测模型并返回统一结构的结果对象。"""
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ProtocolCallError("VALIDATION", f"协议不受支持：{protocol}")

    base = _service_base_url(base_url)
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
        # mimo-v2.5 系列是推理模型，与 api 侧一致：显式关闭思考提速并避免正文为空
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
        # 仅回显状态码，绝不把请求头（含 Key）或上游原文带入异常信息
        raise ProtocolCallError("UPSTREAM", f"上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise ProtocolCallError("TIMEOUT", "上游调用超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise ProtocolCallError("TIMEOUT", "上游调用超时") from exc
        raise ProtocolCallError("UPSTREAM", "上游连接失败") from exc

    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        text = _full_text(protocol, data)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProtocolCallError("UPSTREAM", "上游响应结构异常") from exc

    return AdapterResult(
        text=text,
        usage=_norm_usage(data, anthropic=protocol == "anthropic_messages"),
        raw=data,
        latency_ms=latency_ms,
    )
