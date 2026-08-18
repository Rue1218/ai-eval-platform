"""Agent 协议档的短同步调用助手（MCP 短工具语义的 REST 落地）。

仅供候选生成类接口（数据集 ai-generate、用例 ai-generate / ai-fill）使用：
同步、超时短、只返回文本，不做长任务。被测三协议与 Agent / Judge 共用同一
协议档模型；未配置 Agent 协议档或调用失败时抛出统一 AppError，绝不回显 Key。
"""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from .errors import AppError, ErrorCode
from .models import ProtocolProfile, Setting
from .security import decrypt_secret

# 候选生成属于短工具调用，超过该时长按 TIMEOUT 归一
CALL_TIMEOUT_S = 30


def _resolve_agent_profile(db: Session) -> ProtocolProfile:
    """读取 settings.agent_profile_id 指向的 Agent 协议档。"""
    row = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = row.value if row else None
    if not profile_id:
        raise AppError(ErrorCode.VALIDATION, "未配置 Agent 协议档，请先在协议档页指定 Agent 核心驱动")
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在或已删除，请重新指定")
    if not profile.encrypted_key:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档未配置 API Key")
    return profile


def call_agent_model(db: Session, system: str, user: str, *, max_tokens: int = 2048) -> str:
    """以三协议适配调用 Agent 模型并返回纯文本内容。

    失败语义：上游 4xx/5xx 与连接错误归一为 UPSTREAM；超时归一为 TIMEOUT。
    响应解析失败同样按 UPSTREAM 处理，避免把上游原文抛给浏览器。
    """
    profile = _resolve_agent_profile(db)
    base = profile.base_url.rstrip("/")
    api_key = decrypt_secret(profile.encrypted_key)
    headers = {"Content-Type": "application/json"}

    if profile.protocol == "openai_chat":
        url = f"{base}/v1/chat/completions"
        body = {
            "model": profile.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
        headers["Authorization"] = f"Bearer {api_key}"
        extract = lambda data: data["choices"][0]["message"]["content"]  # noqa: E731
    elif profile.protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body = {
            "model": profile.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
        }
        headers["Authorization"] = f"Bearer {api_key}"
        extract = lambda data: "".join(  # noqa: E731
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    elif profile.protocol == "anthropic_messages":
        url = f"{base}/v1/messages"
        body = {
            "model": profile.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = profile.anthropic_version or "2023-06-01"
        extract = lambda data: "".join(  # noqa: E731
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
    else:
        raise AppError(ErrorCode.VALIDATION, f"Agent 协议档协议不受支持：{profile.protocol}")

    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=CALL_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"Agent 模型上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "Agent 模型调用超时") from exc
    except URLError as exc:
        if "timed out" in str(exc.reason).lower():
            raise AppError(ErrorCode.TIMEOUT, "Agent 模型调用超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型上游连接失败") from exc

    try:
        text = extract(payload)
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型响应结构异常") from exc
    if not text or not text.strip():
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型返回空内容")
    _ = started  # 预留：后续接入 usage_ledger 时统计耗时
    return text


def parse_json_candidates(text: str) -> list[dict]:
    """从模型输出中容错提取 JSON 数组（允许 ```json 代码块或首尾解释文字）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉 markdown 代码围栏
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型未返回可解析的候选 JSON 数组")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型候选 JSON 解析失败") from exc
    if not isinstance(data, list):
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型候选格式不是数组")
    return [item for item in data if isinstance(item, dict)]
