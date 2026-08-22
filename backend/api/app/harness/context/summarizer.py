"""抽取式候选压缩；本阶段不在 Context 包中调用模型生成摘要。"""

from app.harness.contracts.memory import MemoryRecord


def estimate_tokens(text: str) -> int:
    """使用与现网仪表一致的保守字符估算，避免 Context 引入模型依赖。"""
    return max(1, int(len(text) * 1.35)) if text else 0


def compress_record(record: MemoryRecord, *, max_tokens: int) -> str:
    """截断为可追溯摘录；来源由调用方放进 ContextItem.provenance。"""
    if max_tokens <= 0:
        return ""
    max_chars = max(1, int(max_tokens / 1.35))
    text = record.text.strip()
    return text if len(text) <= max_chars else f"{text[:max_chars].rstrip()}…"
