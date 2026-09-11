"""会话标题 AI 生成（结构化输出）。

首条用户消息落库后，用 Agent 协议档把对话开头压缩成简短标题。输出契约
要求单一 JSON 对象 ``{"title": "..."}``：平台两类协议（openai_chat /
anthropic_messages）的原生 ``response_format`` 能力
不一致，这里采用「提示词约定 JSON + 代码侧强校验」的弱结构化方案，
任何协议档都能稳定工作，契约细节见 API.md §4.3 ``session_title``。

本模块只负责「生成 + 解析」，不触碰会话表：落库与 WS 广播由 routers/ws.py
编排。生成全程后台执行，任何失败都降级为消息截断兜底并只记 agent_trace，
绝不影响对话主链路。
"""

import asyncio
import json
import re

from ..db import SessionLocal
from ..errors import AppError
from ..llm_client import call_agent_model
from .log import agent_trace

# 结构化输出提示词：只约定唯一必填字段 title，字段越少幻觉越少。
TITLE_SYSTEM_PROMPT = """你是评测平台的会话命名助手。根据对话的第一条用户消息提炼会话标题，只输出一个 JSON 对象，格式：
{"title": "标题"}
规则：
1. 标题 6-20 字，概括用户的核心意图，不要逐字复制原文；
2. 使用用户消息的主要语言；
3. 不以引号、句号等标点结尾，不含「会话」「对话」等冗余词；
4. 只输出 JSON 对象，不要解释、前缀或代码围栏。"""

# 标题硬上限：模型偶发超长输出时直接截断（正常应落在 6-20 字）。
TITLE_MAX_CHARS = 40
# 送入提示词的首条消息上限，避免粘贴大文档撑爆请求。
PROMPT_TEXT_MAX_CHARS = 500
# 标题生成单独限时：短任务无需沿用 AI 生成的 120s 默认值。
TITLE_TIMEOUT_S = 30.0
# 模型偶尔给标题包一层成对引号，这里统一剥掉。
_TITLE_QUOTE_PAIRS = {('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")}


def fallback_title(text: str, limit: int = 18) -> str:
    """兜底标题：首条消息压缩空白后截断（与前端乐观占位同规则）。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    # 剥离 [引用对话记忆]...[/引用对话记忆] 引用块
    cleaned = re.sub(r"\[引用对话记忆\][\s\S]*?\[/引用对话记忆\]", "", cleaned)
    # 剥离 [引用...] 等前置引用标签
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned)
    # 剥离 markdown 标题符 # 或列表符 * -
    cleaned = re.sub(r"^[#*\-\s]+", "", cleaned)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ""
    if len(cleaned) >= 2 and (cleaned[0], cleaned[-1]) in _TITLE_QUOTE_PAIRS:
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        return ""
    return cleaned[:limit]


def extract_title_payload(raw: str) -> str:
    """从模型输出提取结构化标题；契约不符抛 ``ValueError`` 由调用方兜底。

    解析管线：剥代码围栏 → 截取首个 ``{`` 到末个 ``}`` → ``json.loads``
    → 字段类型校验 → 压缩空白与包裹引号 → 硬限长。弱结构化输出必须在
    代码侧强校验，禁止把模型原文直接写入会话标题。
    """
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出不含 JSON 对象")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("输出不是 JSON 对象")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title 字段缺失或为空")
    title = " ".join(title.split())
    if len(title) >= 2 and (title[0], title[-1]) in _TITLE_QUOTE_PAIRS:
        title = title[1:-1].strip()
    if not title:
        raise ValueError("title 清洗后为空")
    return title[:TITLE_MAX_CHARS]


async def generate_title_text(first_user_text: str) -> str:
    """调用 Agent 协议档生成标题；任何失败回退为消息截断，绝不抛错。

    ``call_agent_model`` 是同步适配器调用，丢线程池执行避免阻塞事件循环；
    数据库会话仅用于解析协议档，用完即关，不与 WS 收包循环共享。
    """
    fallback = fallback_title(first_user_text)
    if not fallback:
        return ""
    db = SessionLocal()
    try:
        user_prompt = f"对话的第一条用户消息：\n{first_user_text[:PROMPT_TEXT_MAX_CHARS]}"
        result = await asyncio.to_thread(
            call_agent_model,
            db,
            TITLE_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=200,
            timeout_s=TITLE_TIMEOUT_S,
        )
        try:
            return extract_title_payload(result.text)
        except ValueError as exc:
            agent_trace(f"session title parse failed type={type(exc).__name__}")
            return fallback
    except AppError as exc:
        # 未配置协议档 / 上游 4xx5xx / 超时：统一降级，不打断对话
        agent_trace(f"session title llm failed code={exc.code.value}")
        return fallback
    except Exception as exc:
        agent_trace(f"session title unexpected type={type(exc).__name__}")
        return fallback
    finally:
        db.close()
