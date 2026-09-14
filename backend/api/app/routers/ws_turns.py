"""Agent 会话回合租约管理（自 ``ws.py`` 抽出）。

承载进程内回合注册表（``_SESSION_TURNS``）与 abort 令牌注册表
（``_SESSION_ABORTS``）及其原子操作：抢占、释放、任务绑定、终态唯一领取。

两个注册表是**进程内共享可变状态**（单副本部署，见 AGENTS.md），本模块是它们
的唯一读写入口——``ws.py`` 侧一律经访问器（``mark_turn_started`` /
``get_active_turn`` / ``get_abort``）操作，不再直接引用容器。这样测试可用
``monkeypatch.setattr(ws_turns, "_SESSION_TURNS", {})`` 隔离状态，且不会与
调用方各自持有不同容器而产生状态分裂。

``ws.py`` 以同名 re-export 保持既有调用点与测试引用（``ws._reserve_turn`` 等）不变。
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from uuid import uuid4

from ..errors import AppError, ErrorCode


@dataclass
class _TurnHandle:
    """会话级 Agent 回合租约，隔离多连接并发与旧任务清理。"""

    turn_id: str
    user_id: str
    abort: asyncio.Event
    task: asyncio.Task[None] | None = None
    started: bool = False
    terminal_emitted: bool = False


# 一个共享会话同一时刻只能有一个交互回合；锁只保护本进程内短临界区，不跨越 await。
_TURN_LOCK = threading.Lock()
_SESSION_TURNS: dict[str, _TurnHandle] = {}
# 会话级 abort 事件注册表（/stop 即时中断；单副本进程内 dict，见 AGENTS.md）
_SESSION_ABORTS: dict[str, asyncio.Event] = {}


def _turn_busy(session_id: str, local_task: asyncio.Task[None] | None = None) -> bool:
    """判断会话是否已有尚未完成的回合，覆盖同会话多条 WebSocket 连接。"""
    if local_task is not None and not local_task.done():
        return True
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        return current is not None and (current.task is None or not current.task.done())


def _reserve_turn(
    session_id: str,
    user_id: str,
    *,
    local_task: asyncio.Task[None] | None = None,
) -> _TurnHandle:
    """原子抢占会话回合；失败时不写入用户消息或恢复令牌。"""
    if local_task is not None and not local_task.done():
        raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is not None and (current.task is None or not current.task.done()):
            raise AppError(ErrorCode.CONCURRENCY, "上一轮 Agent 仍在生成")
        handle = _TurnHandle(
            turn_id=f"{session_id}:{uuid4().hex}",
            user_id=str(user_id),
            abort=asyncio.Event(),
        )
        _SESSION_TURNS[session_id] = handle
        _SESSION_ABORTS[session_id] = handle.abort
        return handle


def _release_turn(handle: _TurnHandle, task: asyncio.Task[None] | None = None) -> None:
    """只清理仍指向当前租约的映射，防止旧任务回调误删新回合 abort。"""
    session_id = handle.turn_id.split(":", 1)[0]
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is not handle:
            return
        if task is not None and current.task is not task:
            return
        _SESSION_TURNS.pop(session_id, None)
        if _SESSION_ABORTS.get(session_id) is handle.abort:
            _SESSION_ABORTS.pop(session_id, None)


def _attach_turn_task(handle: _TurnHandle, task: asyncio.Task[None]) -> None:
    """把后台任务绑定到租约，并用身份校验注册完成回调。"""
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(handle.turn_id.split(":", 1)[0])
        if current is not handle:
            task.cancel()
            raise AppError(ErrorCode.CONCURRENCY, "Agent 回合已失效，请重试")
        handle.task = task
    # stop 可能在 task 首次调度前到达；先让它启动并由 abort 路径发出唯一 completed。
    if handle.abort.is_set() and handle.started:
        task.cancel()
    task.add_done_callback(lambda done: _release_turn(handle, done))


def _claim_terminal(session_id: str, turn_id: str | None) -> bool:
    """为回合抢占唯一完成事件；旧任务或 stop 不得重复发送 completed。"""
    if not turn_id:
        return True
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is None or current.turn_id != turn_id or current.terminal_emitted:
            return False
        current.terminal_emitted = True
        return True


def mark_turn_started(session_id: str, turn_id: str) -> None:
    """标记租约已进入图执行（``/stop`` 与任务绑定据此判定 abort 时序）。"""
    with _TURN_LOCK:
        current = _SESSION_TURNS.get(session_id)
        if current is not None and current.turn_id == turn_id:
            current.started = True


def get_active_turn(session_id: str) -> _TurnHandle | None:
    """读取会话当前租约（无则 None）；加锁读取，供 /stop 与管理动作判定归属。"""
    with _TURN_LOCK:
        return _SESSION_TURNS.get(session_id)


def get_abort(session_id: str) -> asyncio.Event | None:
    """读取会话 abort 令牌（无租约时仍可能残留，供 /stop 兜底置位）。"""
    with _TURN_LOCK:
        return _SESSION_ABORTS.get(session_id)
