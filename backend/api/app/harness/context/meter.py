"""ContextMeter 纯计算：只消费会话窗口契约，不查询数据库或调用模型。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agent.defaults import WINDOW
from app.harness.contracts.context import SessionContextMessage


@dataclass(frozen=True)
class ContextMeter:
    """ContextMeter 扩展度量（包含消息窗口与 Token 级容量统计）。"""

    messages: int
    skills: int
    summary: int
    headroom: int
    window: int = WINDOW
    total_tokens: int = 0
    max_tokens: int = 200000
    messages_tokens: int = 0
    skills_tokens: int = 0
    free_tokens: int = 200000
    used_percent: float = 0.0
    messages_percent: float = 0.0
    skills_percent: float = 0.0
    free_percent: float = 100.0
    mcp_tools_count: int = 0
    mcp_tools_max: int = 28
    memory_files_count: int = 0
    memory_files_max: int = 1

    def as_dict(self) -> dict:
        """返回冻结的 ContextMeter REST 字段。"""
        return {
            "messages": self.messages,
            "skills": self.skills,
            "summary": self.summary,
            "headroom": self.headroom,
            "window": self.window,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "messages_tokens": self.messages_tokens,
            "skills_tokens": self.skills_tokens,
            "free_tokens": self.free_tokens,
            "used_percent": self.used_percent,
            "messages_percent": self.messages_percent,
            "skills_percent": self.skills_percent,
            "free_percent": self.free_percent,
            "mcp_tools_count": self.mcp_tools_count,
            "mcp_tools_max": self.mcp_tools_max,
            "memory_files_count": self.memory_files_count,
            "memory_files_max": self.memory_files_max,
        }


def build_context_meter(
    rows: Sequence[SessionContextMessage],
    *,
    compact_summary: str | None,
    persisted_skill: bool,
    mcp_tools_count: int,
    max_tokens: int,
    skill_id: str | None = None,
) -> ContextMeter:
    """从记忆层读取的窗口素材构造度量，保持 API 字段及估算公式不变。"""
    message_count = len(rows)
    summary_flag = 1 if compact_summary else 0
    skill_flag = 1 if skill_id or persisted_skill else 0
    message_chars = sum(len(row.content) for row in rows)
    messages_tokens = max(0, int(message_chars * 1.35)) + (message_count * 80)
    skills_tokens = 2000 if skill_flag else 0
    summary_tokens = 1200 if summary_flag else 0
    total_tokens = messages_tokens + skills_tokens + summary_tokens
    safe_max_tokens = max(1, max_tokens)
    free_tokens = max(0, safe_max_tokens - total_tokens)
    used_percent = round(min(100.0, (total_tokens / safe_max_tokens) * 100), 1)
    messages_percent = round(min(100.0, (messages_tokens / safe_max_tokens) * 100), 1)
    skills_percent = (
        round(min(100.0, (skills_tokens / safe_max_tokens) * 100), 1) if skill_flag else 0.0
    )
    return ContextMeter(
        messages=message_count,
        skills=skill_flag,
        summary=summary_flag,
        headroom=WINDOW - message_count,
        total_tokens=total_tokens,
        max_tokens=safe_max_tokens,
        messages_tokens=messages_tokens,
        skills_tokens=skills_tokens,
        free_tokens=free_tokens,
        used_percent=used_percent,
        messages_percent=messages_percent,
        skills_percent=skills_percent,
        free_percent=round(max(0.0, 100.0 - used_percent), 1),
        mcp_tools_count=min(max(0, mcp_tools_count), 28),
        mcp_tools_max=28,
        memory_files_count=0,
        memory_files_max=1,
    )
