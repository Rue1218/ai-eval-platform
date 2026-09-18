"""公开思考文本的增量与完成快照核验；绝不读取加密推理字段。"""


class ReasoningText:
    """按输出项、文本种类和段落保留公开摘要，完成快照只补后缀。"""

    def __init__(self):
        self.parts: dict[tuple, str] = {}
        self.done: dict[tuple, str] = {}
        self.emitted = ""

    def record(self, key: tuple, text: str, *, complete: bool) -> None:
        """拒绝不一致的重复完成、完成后增量以及完成文本回退。"""
        if not isinstance(text, str):
            raise ValueError("Responses 思考文本不是字符串")
        if complete:
            if not text.startswith(self.parts.get(key, "")) or self.done.get(key, text) != text:
                raise ValueError("Responses 思考完成快照与增量不一致")
            self.done[key] = text
            self.parts[key] = text
        else:
            if key in self.done:
                raise ValueError("Responses 思考完成后出现增量")
            self.parts[key] = self.parts.get(key, "") + text

    def snapshot(self, index: int, item: dict) -> None:
        """只读取 summary_text/reasoning_text，缺失的已观察段落也属于损坏。"""
        observed = set()
        for field, kind in (("summary", "summary_text"), ("content", "reasoning_text")):
            parts = item.get(field, [])
            if not isinstance(parts, list):
                raise ValueError("Responses 思考快照结构不合法")
            for part_index, part in enumerate(parts):
                if not isinstance(part, dict) or part.get("type") != kind:
                    continue
                key = (index, kind, part_index)
                observed.add(key)
                self.record(key, part.get("text"), complete=True)
        if any(key[0] == index and key not in observed for key in self.parts):
            raise ValueError("Responses 思考快照缺少已观察文本")

    def flush(self) -> list[tuple]:
        """段落之间保留换行；不能通过重写已展示内容掩盖乱序。"""
        text = "\n\n".join(self.parts[key] for key in sorted(self.parts) if self.parts[key])
        if not text.startswith(self.emitted):
            raise ValueError("Responses 思考文本顺序不一致")
        tail = text[len(self.emitted):]
        self.emitted = text
        return [("reasoning", tail)] if tail else []
