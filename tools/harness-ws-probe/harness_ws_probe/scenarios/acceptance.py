"""现行契约验收套件（V1.78 / legacy `/ws/agent`）。

对齐 API.md §4.2–§4.4 现行语义（非 V1.62 历史资料）：
- L0 协议：词汇表版本（event.v5 恒发）、斜杠现行语义（direct 拒绝，仅
  /stop 即时）、非法上行 VALIDATION、幂等、断线重放；
- L2/L3：chat 引擎审计字段、agent 工具回合（tool_call/tool_result 成对）；
- V1.8（dsh 借鉴）：三类卡回执无卡 fail-closed、context_trim/fabrication
  白名单、尽力触发 clarify；
- 产出 AcceptanceReport；不触碰 scripted/CI 旧场景。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ..client import ProbeClient
from ..errors import ProbeError
from ..recorder import TraceFrame

MAX_WAIT_TURN = 180.0


def _payload(frame: TraceFrame) -> dict[str, Any]:
    inner = frame.raw.get("payload")
    return inner if isinstance(inner, dict) else {}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _suffix(text: str, limit: int = 120) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


class AcceptanceReport:
    """验收点记录：name / status（PASS|FAIL|NA|SKIP）/ detail。"""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def record(self, name: str, status: str, detail: str = "") -> None:
        self.items.append({"name": name, "status": status, "detail": detail})
        print(f"[acceptance] {status:<4} {name}  {_suffix(detail)}")

    def summary(self) -> None:
        print("\n== 验收汇总 ==")
        for item in self.items:
            print(f"  {item['status']:<4} {item['name']}")
        passed = sum(1 for i in self.items if i["status"] == "PASS")
        failed = sum(1 for i in self.items if i["status"] == "FAIL")
        na = len(self.items) - passed - failed
        print(f"== {passed} PASS / {failed} FAIL / {na} NA/SKIP")


async def drain(client: ProbeClient, seconds: float = 0.4) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        remain = deadline - asyncio.get_event_loop().time()
        if remain <= 0:
            return
        try:
            await client.recv(timeout_s=remain)
        except (ProbeError, ConnectionError):
            return


async def new_session(client: ProbeClient, title: str) -> None:
    await client.create_session(title=title)
    await client.connect()
