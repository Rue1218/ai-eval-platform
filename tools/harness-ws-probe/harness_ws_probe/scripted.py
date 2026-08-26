"""进程内对等端：按契约回放下行，供 CI 跑同一套 L0/L1 场景。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .errors import ProbeError
from .protocol import CLOSE_SESSION, CLOSE_TICKET
from .recorder import TraceRecorder

HELP_TEXT = (
    "可用命令：\n"
    "- /cancel：取消本会话未完成任务\n"
    "- /stress：打开先评后压确认卡（质量任务 + 自动压测）"
)


def _frame(event: str, event_id: int, payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    return {
        "event": event,
        "session_id": session_id,
        "task_id": None,
        "event_id": event_id,
        "ts": "2026-08-26T06:00:00Z",
        "payload": payload,
    }


class ScriptedProbe:
    """实现与 ProbeClient 相同的发送/等待接口，不连真实 API。"""

    def __init__(self) -> None:
        self.trace = TraceRecorder()
        self.session_id = "sess-scripted"
        self.last_event_id = 0
        self.close_code: int | None = None
        self._seq = 0
        self._queue: list[dict[str, Any]] = []
        self._pending_confirm = False
        self._seen_client_ids: set[str] = set()
        self._completed_rounds = 0
        self._connected = False

    def _emit(self, event: str, payload: dict[str, Any], *, persistent: bool = True) -> dict[str, Any]:
        if persistent:
            self._seq += 1
            eid = self._seq
            self.last_event_id = eid
        else:
            eid = self.last_event_id or 0
        data = _frame(event, eid, payload, self.session_id or "sess-scripted")
        self.trace.record_down(data)
        self._queue.append(data)
        return data

    async def connect(
        self,
        *,
        session_id: str | None = None,
        last_event_id: int = 0,
        ticket: str | None = None,
    ) -> None:
        if ticket == "invalid":
            self.close_code = CLOSE_TICKET
            raise ConnectionClosedScripted(CLOSE_TICKET)
        if session_id == "missing":
            self.close_code = CLOSE_SESSION
            raise ConnectionClosedScripted(CLOSE_SESSION)
        self.session_id = session_id or self.session_id
        self._connected = True
        # 建连后的应用层 pong 为瞬态
        pong = {
            "event": "pong",
            "session_id": self.session_id,
            "task_id": None,
            "event_id": last_event_id,
            "ts": "2026-08-26T06:00:00Z",
            "payload": {},
        }
        self.trace.record_down(pong)
        self._queue.append(pong)
        # 重连：只补发 event_id > last 的持久事件（本桩用已录制下行模拟）
        if last_event_id > 0:
            for item in list(self.trace.downlink()):
                if item.persistent and item.event_id and item.event_id > last_event_id:
                    self._queue.append(item.raw)

    async def disconnect(self) -> None:
        self._connected = False
        self._queue.clear()

    async def close(self) -> None:
        await self.disconnect()

    async def send_user_message(
        self,
        text: str,
        *,
        attachments: list[dict[str, str]] | None = None,
        client_message_id: str | None = None,
    ) -> None:
        self.trace.record_up(
            {
                "event": "user_message",
                "payload": {
                    "text": text,
                    "attachments": attachments or [],
                    **({"client_message_id": client_message_id} if client_message_id else {}),
                },
            }
        )
        stripped = text.strip()
        if client_message_id and client_message_id in self._seen_client_ids:
            return
        if client_message_id:
            self._seen_client_ids.add(client_message_id)
        if stripped.startswith("/cancel"):
            self._emit("error", {"code": "VALIDATION", "message": "当前会话没有可取消的任务"})
            return
        if stripped.startswith("/stress"):
            self._pending_confirm = True
            self._emit(
                "confirm",
                {
                    "kind": "benchmark",
                    "with_stress": True,
                    "profile_ids": ["live-p"],
                    "dataset_id": "d1",
                    "run": {"sample_size": 1000},
                },
            )
            return
        if stripped.startswith("/help"):
            self._emit("user_message", {"content": "/help", "role": "user"})
            self._emit("assistant_message", {"text": HELP_TEXT, "role": "assistant"})
            self._emit("response.completed", {"finish_reason": "stop", "role": "assistant"})
            self._completed_rounds += 1
            return
        self._emit("user_message", {"content": stripped, "role": "user"})
        # 闲聊按 API.md：思考增量（瞬态）→ 正文 → think_final → completed
        self._emit(
            "thought",
            {"text": "先判断用户是在闲聊还是下单。", "stream": "think"},
            persistent=False,
        )
        self._emit(
            "thought",
            {"text": "无需工具，直接用一句话回答。", "stream": "think"},
            persistent=False,
        )
        self._emit(
            "assistant_delta",
            {"role": "assistant", "text": "ok"},
            persistent=False,
        )
        self._emit("assistant_message", {"text": "ok", "role": "assistant"})
        self._emit(
            "thought",
            {
                "text": "先判断用户是在闲聊还是下单。无需工具，直接用一句话回答。",
                "stream": "think_final",
            },
        )
        self._emit("response.completed", {"finish_reason": "stop", "role": "assistant"})
        self._completed_rounds += 1

    async def send_confirm_ack(self, ok: bool, patch: dict[str, Any] | None = None) -> None:
        self.trace.record_up({"event": "confirm_ack", "payload": {"ok": ok, "patch": patch or {}}})
        if not self._pending_confirm:
            self._emit("error", {"code": "VALIDATION", "message": "没有待确认卡"})
            return
        self._pending_confirm = False
        if ok:
            merged = dict(patch or {})
            sample = (merged.get("run") or {}).get("sample_size")
            if sample != 1 or merged.get("with_stress") is not False:
                self._emit("error", {"code": "VALIDATION", "message": "L1 入队必须 sample_size=1 且关闭压测"})
                return
            self._emit("confirm_ack", {"ok": True, "task_id": uuid4().hex, "message": "已入队"})
        else:
            self._emit("confirm_ack", {"ok": False, "task_id": None, "message": "已取消确认"})

    async def send_clarify_reply(self, clarify_id: str, answer: str) -> None:
        self.trace.record_up(
            {"event": "clarify_reply", "payload": {"id": clarify_id, "answer": answer}}
        )

    async def send_cancel_task(self, task_id: str) -> None:
        self.trace.record_up({"event": "cancel_task", "payload": {"task_id": task_id}})

    async def send_raw(self, message: dict[str, Any]) -> None:
        self.trace.record_up(message)
        event = message.get("event")
        if event not in {"user_message", "confirm_ack", "cancel_task", "clarify_reply"}:
            self._emit("error", {"code": "VALIDATION", "message": "不支持的 WebSocket 事件"})

    async def recv(self, timeout_s: float = 15.0) -> dict[str, Any]:
        if self._queue:
            return self._queue.pop(0)
        raise ProbeError("等待下行超时")

    async def wait_event(self, name: str, timeout_s: float = 20.0) -> dict[str, Any]:
        while self._queue:
            data = self._queue.pop(0)
            if data.get("event") == name:
                return data
        raise ProbeError(f"未等到下行事件 {name}")

    async def drain(self, seconds: float = 0.4) -> None:
        return None


class ConnectionClosedScripted(Exception):
    """脚本对等端在握手阶段关闭。"""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code
