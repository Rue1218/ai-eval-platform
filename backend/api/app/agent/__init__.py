"""基于 LangGraph 的 Agent 运行入口（骨架版）。

公开入口统一承载纯对话流式生成与记忆检查点（骨架化后不再包含范式路由、
ReAct 思考链、确认卡与澄清卡）。
"""

from .graph import LangGraphAgent

__all__ = ["LangGraphAgent"]
