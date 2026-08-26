"""上下行帧录制器：内存列表 + 可选 jsonl。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .protocol import is_transient
from .redact import redact

Direction = Literal["up", "down"]


@dataclass(slots=True)
class TraceFrame:
    """单帧：方向、相对毫秒、事件名、是否持久、脱敏后的 JSON。"""

    dir: Direction
    t_ms: int
    event: str
    event_id: int | None
    persistent: bool
    raw: dict[str, Any]


class TraceRecorder:
    """按发送/接收顺序记录帧，供 ExpectMatcher 与 --dump 使用。"""

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.frames: list[TraceFrame] = []

    def _t_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def record_up(self, message: dict[str, Any]) -> TraceFrame:
        event = str(message.get("event") or "")
        frame = TraceFrame(
            dir="up",
            t_ms=self._t_ms(),
            event=event,
            event_id=None,
            persistent=True,
            raw=redact(dict(message)),
        )
        self.frames.append(frame)
        return frame

    def record_down(self, message: dict[str, Any]) -> TraceFrame:
        payload = message if isinstance(message, dict) else {}
        event = str(payload.get("event") or "")
        event_id = payload.get("event_id")
        frame = TraceFrame(
            dir="down",
            t_ms=self._t_ms(),
            event=event,
            event_id=event_id if isinstance(event_id, int) else None,
            persistent=not is_transient(payload),
            raw=redact(dict(payload)),
        )
        self.frames.append(frame)
        return frame

    def downlink(self) -> list[TraceFrame]:
        return [item for item in self.frames if item.dir == "down"]

    def uplink(self) -> list[TraceFrame]:
        return [item for item in self.frames if item.dir == "up"]

    def dump_text(self) -> str:
        """人类可读时间线（CLI --dump）。"""
        lines: list[str] = []
        for item in self.frames:
            mark = "↑" if item.dir == "up" else "↓"
            persist = "P" if item.persistent else "T"
            eid = f"#{item.event_id}" if item.event_id is not None else "-"
            lines.append(f"{item.t_ms:>6}ms {mark} {persist} {eid} {item.event}")
        return "\n".join(lines)

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for item in self.frames:
                handle.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
