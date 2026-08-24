"""LLM 裁判：用裁判协议档对目标模型输出评 0–100 质量分。

设计原则（对齐 scoring.py 的零/少依赖纯函数风格，便于单测）：
- ``build_judge_messages`` 组装裁判输入（问题 + 标准参考 + 可选背景 + 待评回答）；
- ``parse_judge_output`` 防御式解析裁判输出：JSON 优先、数字回退、越界置 None，
  解析失败不抛异常、不中断整次评测；
- ``judge_single_sample`` 调 ``call_protocol`` 完成单样本裁判，失败样本
  ``judge_score=None`` 且 ``error`` 非空，与目标调用失败语义一致。

裁判调用参数：``temperature=0`` 保证可复现；``max_tokens`` 收紧（默认 300，
只输出 JSON 分数）；``timeout_s`` 沿用任务 run 配置。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .protocol import ProtocolCallError, call_protocol

# 裁判默认输出上限：只允许 JSON 分数对象，无需长文本。
# 推理模型即使禁用 thinking 也可能输出稍长理由，留 300 token 余量
JUDGE_MAX_TOKENS = 300

JUDGE_SYSTEM_PROMPT = """你是严谨的问答质量评审员。请根据标准参考答案，对模型回答评 0-100 的整数分。
评分锚点：
- 90-100：完全正确且完整，覆盖参考答案全部要点
- 70-89：基本正确，覆盖大部分要点，或存在轻微不准确
- 40-69：部分正确，覆盖部分要点，或存在明显错误
- 1-39：仅少量相关，大部分偏离参考答案
- 0：完全无关或拒绝回答
必须严格只输出 JSON（不要输出任何其他文字）：
{"score": <0-100整数>, "reason": "<不超过50字的一句话理由>"}"""

# 数字回退：从文本中提取首个 1-3 位数字（含 "85分" / "得分85" 等口语化输出）；
# 前置负号/数字用负向后顾排除，避免把 "-3" 判成 3、把 "150" 截成 "15"
_NUMBER_RE = re.compile(r"(?<!-)(?<!\d)(\d{1,3})(?!\d)")
# 输出文本上限，防裁判超长回复占满 raw/usage 空间
_RAW_MAX = 32 * 1024


def build_judge_messages(item_data: dict[str, Any]) -> list[dict[str, str]]:
    """组装裁判 user 消息：背景 + 问题 + 标准参考 + 待评回答。

    ``item_data`` 结构：{question, reference, context, output}。
    """
    question = item_data.get("question") or ""
    reference = item_data.get("reference") or ""
    output = item_data.get("output") or ""
    context = (item_data.get("context") or "").strip()

    parts = []
    if context:
        parts.append(f"背景信息:\n{context}")
    parts.append(f"问题:{question}")
    parts.append(f"标准参考答案:{reference or '（无）'}")
    parts.append(f"待评审的模型回答:\n{output or '（空）'}")
    user_content = "\n\n".join(parts)
    user_content += "\n\n请按系统要求输出 JSON 分数。"
    return [{"role": "user", "content": user_content}]


def parse_judge_output(text: str) -> tuple[int | None, str | None]:
    """解析裁判输出为 ``(score, reason)``。

    - 优先 ``json.loads`` 取 ``score`` / ``reason``；
    - JSON 失败回退提取首个数字；
    - ``score`` 非 0-100 整数、或完全无法解析时返回 ``(None, None)``。
    """
    if not text or not text.strip():
        return None, None
    raw = text.strip()
    score: int | None = None
    reason: str | None = None

    # JSON 优先：允许裁判在 JSON 前后夹带少量文字（截取首个 {...} 片段）
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            payload = json.loads(raw[start : end + 1])
            if isinstance(payload, dict):
                value = payload.get("score")
                if isinstance(value, int) and not isinstance(value, bool):
                    score = value
                elif isinstance(value, float):
                    score = int(value)
                elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
                    score = int(value.strip())
                reason_raw = payload.get("reason")
                if isinstance(reason_raw, str) and reason_raw.strip():
                    reason = reason_raw.strip()
        except (ValueError, TypeError):
            pass

    # 数字回退：JSON 解析失败或 score 缺失时，取首个 1-3 位数字
    if score is None:
        match = _NUMBER_RE.search(raw)
        if match:
            try:
                score = int(match.group(1))
            except ValueError:
                score = None

    if score is None or not 0 <= score <= 100:
        return None, None
    if reason and len(reason) > 500:
        reason = reason[:500]
    return score, reason


def judge_single_sample(
    judge_kwargs: dict[str, Any],
    item_data: dict[str, Any],
    truncate_raw_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """调裁判协议档对单个目标样本打分。

    返回 ``{ok, judge_score, judge_reason, latency_ms, usage, raw, error}``；
    ``ok=False`` 时 ``judge_score=None``、``error`` 非空（含解析失败）。
    """
    messages = build_judge_messages(item_data)
    try:
        result = call_protocol(messages=messages, **judge_kwargs)
    except ProtocolCallError as exc:
        return {"ok": False, "error": f"{exc.code}: {exc.message}"}
    text = result.text or ""
    score, reason = parse_judge_output(text)
    if score is None:
        return {
            "ok": False,
            "error": "JUDGE_PARSE: 裁判输出无法解析为 0-100 分数",
            "latency_ms": result.latency_ms,
            "usage": result.usage,
            "raw": truncate_raw_fn(result.raw) if result.raw else None,
        }
    return {
        "ok": True,
        "judge_score": score,
        "judge_reason": reason,
        "latency_ms": result.latency_ms,
        "usage": result.usage,
        "raw": truncate_raw_fn(result.raw) if result.raw else None,
    }


def build_judge_call_kwargs(
    *,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str,
    anthropic_version: str | None,
    timeout_s: float,
    max_tokens: int = JUDGE_MAX_TOKENS,
) -> dict[str, Any]:
    """构造裁判调用参数：系统提示为评审 prompt，temperature=0 保证可复现。"""
    return {
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "anthropic_version": anthropic_version,
        "system": JUDGE_SYSTEM_PROMPT,
        "temperature": 0,
        "max_tokens": max_tokens,
        "timeout_s": timeout_s,
    }
