"""Agent 子系统的最小安全追踪入口。"""

from __future__ import annotations

import sys


def agent_trace(message: str) -> None:
    """向容器 stderr 输出脱敏后的简短运行轨迹。"""
    print(f"[agent] {message}", file=sys.stderr, flush=True)
