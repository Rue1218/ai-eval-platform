"""单 API 副本下的共享会话瞬态流连接 Hub。

Worker 产生的持久化事件仍通过 ``ws_events`` 轮询转发；本模块只负责不落库的
正文 chunk 广播。产品当前部署为单 API 副本，若扩容为多副本必须替换为 Redis
Pub/Sub 等进程外总线，不能把本 Hub 当作跨进程一致性机制。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


@dataclass(frozen=True)
class LiveSessionConnection:
    """已认证的会话连接及其独立发送游标/锁。"""

    connection_id: str
    session_id: str
    user_id: str
    websocket: WebSocket
    state: Any


class SessionConnectionHub:
    """按会话登记在线连接，并安全广播正文流式增量。"""

    def __init__(self) -> None:
        self._connections: dict[str, dict[str, LiveSessionConnection]] = {}

    def register(
        self,
        connection_id: str,
        session_id: str,
        user_id: str,
        websocket: WebSocket,
        state: Any,
    ) -> None:
        """登记已通过会话可见性校验的长连接。"""
        self._connections.setdefault(session_id, {})[connection_id] = LiveSessionConnection(
            connection_id=connection_id,
            session_id=session_id,
            user_id=user_id,
            websocket=websocket,
            state=state,
        )

    def unregister(self, session_id: str, connection_id: str) -> None:
        """按唯一连接 ID 注销，避免旧连接清掉同会话的新重连。"""
        rows = self._connections.get(session_id)
        if not rows:
            return
        rows.pop(connection_id, None)
        if not rows:
            self._connections.pop(session_id, None)

    async def broadcast_chunk(
        self,
        session_id: str,
        build_frame: Callable[[int], dict],
    ) -> None:
        """向会话内在线成员并发发送正文 chunk；慢/失效连接会被清理。

        ``build_frame`` 每个接收者单独按其 cursor 构造帧，避免共享发起者的
        event_id；发送与该连接的 Worker 事件转发共用 state.lock。
        """
        rows = list(self._connections.get(session_id, {}).values())
        if not rows:
            return

        async def _send(row: LiveSessionConnection) -> str | None:
            frame = build_frame(int(getattr(row.state, "cursor", 0)))
            try:
                async with row.state.lock:
                    await asyncio.wait_for(row.websocket.send_json(frame), timeout=1.0)
            except Exception:
                return row.connection_id
            return None

        failed = await asyncio.gather(*(_send(row) for row in rows))
        for connection_id in (item for item in failed if item):
            self.unregister(session_id, connection_id)

    async def broadcast_event(self, session_id: str, frame: dict) -> bool:
        """向会话在线成员广播同一条持久化事件，并同步各连接事件游标。"""
        rows = list(self._connections.get(session_id, {}).values())
        if not rows:
            return False

        async def _send(row: LiveSessionConnection) -> str | None:
            try:
                async with row.state.lock:
                    await asyncio.wait_for(row.websocket.send_json(frame), timeout=1.0)
                    row.state.cursor = max(
                        int(getattr(row.state, "cursor", 0)),
                        int(frame.get("event_id", 0)),
                    )
            except Exception:
                return row.connection_id
            return None

        failed = await asyncio.gather(*(_send(row) for row in rows))
        for connection_id in (item for item in failed if item):
            self.unregister(session_id, connection_id)
        return any(item is None for item in failed)

    async def close_non_owner(self, session_id: str, owner_id: str) -> None:
        """会话取消分享时立刻关闭协作者连接，阻止继续接收瞬态数据。"""
        rows = [
            row
            for row in self._connections.get(session_id, {}).values()
            if row.user_id != owner_id
        ]
        await self._close_rows(rows)

    async def close_all(self, session_id: str) -> None:
        """软删除会话后关闭全部连接，后续访问统一由 4404 表达。"""
        await self._close_rows(list(self._connections.get(session_id, {}).values()))

    async def _close_rows(self, rows: list[LiveSessionConnection]) -> None:
        """关闭指定连接并从 Hub 移除；关闭异常不影响已完成的数据库事务。"""
        async def _close(row: LiveSessionConnection) -> None:
            try:
                async with row.state.lock:
                    await row.websocket.close(code=4404)
            except Exception:
                pass
            finally:
                self.unregister(row.session_id, row.connection_id)

        if rows:
            await asyncio.gather(*(_close(row) for row in rows))


# 当前 Compose 为单 API 副本；连接 Hub 仅作为该进程内的瞬态广播通道。
SESSION_CONNECTION_HUB = SessionConnectionHub()
