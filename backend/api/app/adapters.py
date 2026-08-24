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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import AppError, ErrorCode

# 契约支持的三种协议（与 protocol_profiles 的 CHECK 约束一致）
SUPPORTED_PROTOCOLS = ("openai_chat", "openai_responses", "anthropic_messages")

# 非流式调用被测 / Agent 模型的默认超时秒数
DEFAULT_TIMEOUT_S = 30.0
# 建连 + 响应头；正文首 token 在读循环里按切片等待，避免整段 timeout_s 卡死。
CONNECT_TIMEOUT_S = 15.0
# 读流切片：到期后检查取消与总时限，再继续等下一刀。
STREAM_READ_SLICE_S = 2.0

# 仅对已知支持 reasoning 控制的模型发送 OpenAI 专用字段，避免普通模型因未知字段报错。
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")
_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def _is_openai_reasoning_model(model: str) -> bool:
    """判断模型名是否属于 OpenAI/o 系列或明确的推理模型。"""
    normalized = model.strip().lower()
    return normalized.startswith(_OPENAI_REASONING_PREFIXES) or any(
        marker in normalized for marker in ("reasoner", "reasoning", "deepseek-r1")
    )


def _openai_reasoning_effort(model: str, enabled: bool, effort: str) -> str | None:
    """返回可发送的 OpenAI effort；普通模型不携带推理专用字段。"""
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


def _close_quietly(response: object) -> None:
    """取消或超时时关掉上游连接，忽略二次 close 异常。"""
    closer = getattr(response, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            return


def _arm_read_timeout(response: object, seconds: float) -> None:
    """把已建立连接的读超时切成短片，便于块间检查取消。夹具无 socket 时跳过。"""
    try:
        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None) if fp is not None else None
        sock = getattr(raw, "_sock", None) if raw is not None else None
        if sock is not None:
            sock.settimeout(seconds)
    except Exception:
        return


def _is_wait_timeout(exc: BaseException) -> bool:
    """socket / urllib 在切片读超时后抛出的等待类异常。"""
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ in {"timeout", "TimeoutError"}


def _iter_stream_lines(
    response: object,
    *,
    deadline: float,
    should_abort: Callable[[], bool] | None,
    slice_s: float = STREAM_READ_SLICE_S,
) -> Iterator[bytes]:
    """按切片读取 SSE 行：总时限内可中断，取消后立即停读。"""
    _arm_read_timeout(response, slice_s)
    iterator = iter(response)  # type: ignore[arg-type]
    while True:
        if should_abort is not None and should_abort():
            _close_quietly(response)
            raise StreamAborted()
        if time.monotonic() > deadline:
            _close_quietly(response)
            raise TimeoutError("stream deadline exceeded")
        try:
            raw_line = next(iterator)
        except StopIteration:
            break
        except Exception as exc:
            if _is_wait_timeout(exc):
                continue
            raise
        yield raw_line


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
    reasoning_enabled: bool = False,
    reasoning_effort: str = "medium",
) -> AdapterResult:
    """按协议适配调用上游模型并返回统一结构的结果对象。

    ``messages`` 为 ``[{"role": "user" | "assistant", "content": "..."}]``；
    系统提示词经 ``system`` 独立传入，由各协议以自身字段承载
    （chat 的 system 消息 / responses 的 instructions / anthropic 的 system）。
    """
    if protocol not in SUPPORTED_PROTOCOLS:
        raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{protocol}")

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
        headers["Authorization"] = f"Bearer {api_key}"

    elif protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body = {"model": model, "input": list(messages), "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=True,
        )
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
        if reasoning_enabled and _supports_anthropic_thinking(model):
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": _anthropic_thinking_budget(max_tokens, reasoning_effort),
            }
            # Anthropic extended thinking 要求 temperature 使用默认值 1。
            body["temperature"] = 1.0
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
    should_abort: Callable[[], bool] | None = None,
    reasoning_enabled: bool = True,
    reasoning_effort: str = "medium",
) -> Iterator[tuple[str, str]]:
    """按协议流式调用上游模型，逐块 yield ``(kind, text)`` 增量（SSE）。

    ``kind`` 为增量类别：``"content"`` 是正式回复正文，``"reasoning"``
    是推理模型的前置思考链（deepseek 风格 ``reasoning_content`` /
    anthropic ``thinking_delta`` / responses ``reasoning_summary``），
    供前端思考卡展示；上游未产生思考链时全程只 yield content。

    ``timeout_s`` 约束整体流式时长；建连用较短 ``CONNECT_TIMEOUT_S``，
    读体按 ``STREAM_READ_SLICE_S`` 切片以便 ``should_abort`` 生效。
    超时归一为 TIMEOUT，上游 4xx/5xx 归一为 UPSTREAM。若网关忽略
    ``stream`` 参数直接返回完整 JSON（非 SSE），则兜底解析全文并作为
    单块 content yield，保证调用方拿到正确结果而非空流降级。
    """
    if protocol not in SUPPORTED_PROTOCOLS:
        raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{protocol}")

    base = _service_base_url(base_url)
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
        # 流式思考是否开启由 Agent 设置控制；默认值保持 Mimo 旧行为（开启）。
        _apply_compatible_thinking(body, base, model, reasoning_enabled, reasoning_effort)
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=False,
        )
        headers["Authorization"] = f"Bearer {api_key}"

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

    elif protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body = {"model": model, "input": list(messages), "stream": True, "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        _apply_openai_reasoning(
            body,
            model=model,
            enabled=reasoning_enabled,
            effort=reasoning_effort,
            responses=True,
        )
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
        if reasoning_enabled and _supports_anthropic_thinking(model):
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": _anthropic_thinking_budget(max_tokens, reasoning_effort),
            }
            body["temperature"] = 1.0
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

    if should_abort is not None and should_abort():
        raise StreamAborted()

    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    deadline = time.monotonic() + timeout_s
    connect_timeout = min(timeout_s, CONNECT_TIMEOUT_S)
    try:
        response = urlopen(request, timeout=connect_timeout)
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
            for raw_line in _iter_stream_lines(
                response,
                deadline=deadline,
                should_abort=should_abort,
            ):
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
    except StreamAborted:
        raise
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
                models_list.append({
                    "id": m_id,
                    "name": str(item.get("display_name") or item.get("name") or m_id),
                    "owned_by": str(item.get("owned_by") or item.get("root") or ("anthropic" if protocol == "anthropic_messages" else "remote")),
                })
    elif isinstance(data, dict):
        raw_items = data.get("data") or data.get("models") or data.get("items") or []
        if isinstance(raw_items, dict) and isinstance(raw_items.get("models"), list):
            raw_items = raw_items["models"]
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict) and (item.get("id") or item.get("name") or item.get("display_name")):
                    m_id = str(item.get("id") or item.get("name") or item.get("display_name"))
                    models_list.append({
                        "id": m_id,
                        "name": str(item.get("display_name") or item.get("name") or m_id),
                        "owned_by": str(item.get("owned_by") or item.get("root") or ("anthropic" if protocol == "anthropic_messages" else ("ollama" if "models" in data else "remote"))),
                    })

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
