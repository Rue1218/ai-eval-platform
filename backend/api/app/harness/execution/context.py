"""工具执行运行时上下文。

该对象只在一次 ToolNode 调用期间存在，承载会话、用户与沙箱等平台注入
信息。它不进入 GraphState、检查点、模型参数或 WebSocket 事件，因此模型不能
伪造工作目录、用户身份或资源归属。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """工具执行上下文（仅运行时，不序列化）。"""

    session_id: str = ""
    user_id: str = ""
    thread_id: str = ""
    sandbox_dir: str | None = None
    owned_file_ids: frozenset[str] = frozenset()
    call_id: str = ""
