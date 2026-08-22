"""基于 LangGraph 的 Agent 运行入口。

当前只实现单轮文本调用；工具、确认卡、记忆和长任务等能力不在本轮恢复。
"""

from .graph import LangGraphAgent

__all__ = ["LangGraphAgent"]
