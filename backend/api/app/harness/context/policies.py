"""窗口优先级与槽位上限；系统和用户输入永不因预算被降级。"""

from dataclasses import dataclass

IMMUTABLE_SLOTS = frozenset({"system", "user_input"})
# 会话摘要与系统同处前部，用户输入后紧跟本轮 observation，避免证据掉进窗口中段。
SLOT_ORDER = ("system", "session_state", "user_input", "observation", "knowledge", "history")


@dataclass(frozen=True)
class WindowPolicy:
    """最小窗口策略；数字只是内部预算，不改变对外 ContextMeter 字段。"""

    max_tokens: int = 8000
    session_state_ratio: float = 0.15
    observation_ratio: float = 0.25
    knowledge_ratio: float = 0.30
    history_ratio: float = 0.30

    def slot_budget(self, slot: str) -> int:
        """计算可降级槽位的最大预算，未知槽位默认不给预算。"""
        ratios = {
            "session_state": self.session_state_ratio,
            "observation": self.observation_ratio,
            "knowledge": self.knowledge_ratio,
            "history": self.history_ratio,
        }
        return int(self.max_tokens * ratios.get(slot, 0.0))
