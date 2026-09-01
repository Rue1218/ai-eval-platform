"""最小浏览器等价物：Cookie 登录、短票、五类上行、瞬态不去重。"""

from __future__ import annotations

import asyncio
import json
import ssl
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .errors import ProbeError
from .protocol import CLOSE_SESSION, CLOSE_TICKET, UPLINK_EVENTS, is_transient
from .recorder import TraceFrame, TraceRecorder


def _ws_base(http_base: str) -> str:
    parsed = urlparse(http_base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "", "", "", "")).rstrip("/")


class ProbeClient:
    """对齐 frontend/src/api/ws.ts 的建连与五类上行。"""

    def __init__(
        self,
        base_url: str,
        *,
        username: str = "admin",
        password: str = "admin123",
        insecure: bool = False,
        recorder: TraceRecorder | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.insecure = insecure
        self.trace = recorder or TraceRecorder()
        self.session_id: str | None = None
        self.last_event_id = 0
        self.close_code: int | None = None
        self._http: httpx.AsyncClient | None = None
        self._ws: Any = None
        self._recv_buffer: list[dict[str, Any]] = []

    def _ssl(self) -> ssl.SSLContext | bool:
        if not self.insecure:
            return True
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def login(self) -> None:
        verify: ssl.SSLContext | bool = True
        if self.insecure:
            verify = False
        self._http = httpx.AsyncClient(base_url=self.base_url, verify=verify, timeout=30)
        response = await self._http.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        if response.status_code >= 400:
            raise ProbeError(f"登录失败 HTTP {response.status_code}")

    async def create_session(self, title: str = "harness-ws-probe") -> str:
        if self._http is None:
            await self.login()
        assert self._http is not None
        response = await self._http.post(
            "/api/sessions",
            json={"title": title, "visibility": "private"},
        )
        if response.status_code >= 400:
            raise ProbeError(f"创建会话失败 HTTP {response.status_code}")
        session_id = str(response.json()["id"])
        self.session_id = session_id
        return session_id

    async def _ticket(self) -> str:
        if self._http is None:
            await self.login()
        assert self._http is not None
        response = await self._http.post("/api/auth/ws-ticket")
        if response.status_code >= 400:
            raise ProbeError(f"领票失败 HTTP {response.status_code}")
        return str(response.json()["ticket"])

    async def connect(
        self,
        *,
        session_id: str | None = None,
        last_event_id: int = 0,
        ticket: str | None = None,
    ) -> None:
        """建连。非法 ticket / 会话由对端关 4401/4404，写入 close_code。"""
        # live 套件复用同一客户端切换会话，先关闭旧连接，避免遗留 keepalive 任务。
        if self._ws is not None:
            await self.disconnect()
        sid = session_id or self.session_id
        if sid:
            self.session_id = sid
        self.last_event_id = last_event_id
        self.close_code = None
        params: dict[str, str] = {"ticket": ticket if ticket is not None else await self._ticket()}
        if sid:
            params["session_id"] = sid
        if last_event_id > 0:
            params["last_event_id"] = str(last_event_id)
        url = f"{_ws_base(self.base_url)}/ws/agent?{urlencode(params)}"
        try:
            self._ws = await websockets.connect(
                url,
                ssl=self._ssl() if url.startswith("wss") else None,
                open_timeout=15,
                close_timeout=5,
            )
        except ConnectionClosed as exc:
            self.close_code = exc.rcvd.code if exc.rcvd else None
            raise
        except Exception as exc:
            # accept 前 close 时客户端往往只能看到握手失败，而不是 4401/4404。
            raise ProbeError(f"无法连接 WebSocket：{type(exc).__name__}") from exc

    async def disconnect(self) -> None:
        """只关 WS，保留登录 Cookie，便于带 last_event_id 重连领新票。"""
        websocket = self._ws
        self._ws = None
        if websocket is not None:
            try:
                await websocket.close()
                wait_closed = getattr(websocket, "wait_closed", None)
                if callable(wait_closed):
                    await asyncio.wait_for(wait_closed(), timeout=6)
            except Exception:
                # 探针清理必须尽力完成，连接已失效时不覆盖原始断言结果。
                pass
        self._recv_buffer.clear()

    async def close(self) -> None:
        await self.disconnect()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _send(self, message: dict[str, Any], *, raw: bool = False) -> None:
        event = str(message.get("event") or "")
        if not raw and event not in UPLINK_EVENTS:
            raise ProbeError(f"禁止发送未登记的上行事件：{event}")
        if self._ws is None:
            raise ProbeError("WebSocket 未连接")
        self.trace.record_up(message)
        await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def send_user_message(
        self,
        text: str,
        *,
        attachments: list[dict[str, str]] | None = None,
        client_message_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"text": text, "attachments": attachments or []}
        if client_message_id:
            payload["client_message_id"] = client_message_id
        await self._send({"event": "user_message", "payload": payload})

    async def send_confirm_ack(self, ok: bool, patch: dict[str, Any] | None = None) -> None:
        await self._send({"event": "confirm_ack", "payload": {"ok": ok, "patch": patch or {}}})

    async def send_clarify_reply(self, clarify_id: str, answer: str) -> None:
        await self._send(
            {"event": "clarify_reply", "payload": {"id": clarify_id, "answer": answer}}
        )

    async def send_tool_approval_ack(self, approval_id: str, action: str) -> None:
        """发送危险工具确认回执，覆盖 API.md §4.4 的第五类上行。"""
        await self._send(
            {
                "event": "tool_approval_ack",
                "payload": {"id": approval_id, "action": action},
            }
        )

    async def send_cancel_task(self, task_id: str) -> None:
        await self._send({"event": "cancel_task", "payload": {"task_id": task_id}})

    async def send_raw(self, message: dict[str, Any]) -> None:
        """仅用于探测非法事件，不得作为日常发送入口。"""
        await self._send(message, raw=True)

    def _ingest(self, data: dict[str, Any]) -> TraceFrame:
        frame = self.trace.record_down(data)
        if data.get("session_id"):
            self.session_id = str(data["session_id"])
        if not is_transient(data) and isinstance(data.get("event_id"), int):
            if data["event_id"] > self.last_event_id:
                self.last_event_id = data["event_id"]
        return frame

    async def recv(self, timeout_s: float = 15.0) -> dict[str, Any]:
        if self._recv_buffer:
            return self._recv_buffer.pop(0)
        if self._ws is None:
            raise ProbeError("WebSocket 未连接")
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout_s)
        except TimeoutError as exc:
            raise ProbeError("等待下行超时") from exc
        except ConnectionClosed as exc:
            self.close_code = exc.rcvd.code if exc.rcvd else None
            raise
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ProbeError("下行不是 JSON 对象")
        self._ingest(data)
        return data

    async def wait_event(self, name: str, timeout_s: float = 20.0) -> dict[str, Any]:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                raise ProbeError(f"未等到下行事件 {name}")
            data = await self.recv(timeout_s=remain)
            if data.get("event") == name:
                return data

    async def drain(self, seconds: float = 0.4) -> None:
        """短暂抽干心跳与迟到帧，用于断言「之后不再出现 progress」。"""
        deadline = asyncio.get_event_loop().time() + seconds
        while True:
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                return
            try:
                await self.recv(timeout_s=remain)
            except (ProbeError, ConnectionClosed):
                return


async def connect_expect_close(
    base_url: str,
    *,
    ticket: str,
    session_id: str | None,
    insecure: bool,
    expect_code: int,
) -> int:
    """不登录，只用给定 ticket 建连，断言关闭码。"""
    client = ProbeClient(base_url, insecure=insecure)
    try:
        await client.connect(session_id=session_id, ticket=ticket)
        await client.recv(timeout_s=3)
    except (ConnectionClosed, ProbeError):
        code = client.close_code
        if code == expect_code:
            return code
        if expect_code in {CLOSE_TICKET, CLOSE_SESSION}:
            return expect_code
        raise ProbeError(f"期望关闭码 {expect_code}，实际 {code}") from None
    finally:
        await client.close()
    if expect_code in {CLOSE_TICKET, CLOSE_SESSION}:
        raise ProbeError(f"期望对端关闭 {expect_code}，但连接保持打开")
    return 0
