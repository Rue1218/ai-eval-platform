"""新循环可取消审批闸门；卡片事务和回执身份验证由主 Runtime 接线。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

ApprovalGate = Callable[[dict[str, Any]], Awaitable[str]]
DECISIONS = ("allow", "deny", "always")


class ApprovalBroker:
    """按会话及授权 scope 隔离临时授权，生命周期由 Runtime 管理。"""

    def __init__(self) -> None:
        """授权只驻留当前进程，关闭 Runtime 时必须 clear_session。"""
        self._gates: dict[str, ApprovalGate] = {}
        self._always_allowed: dict[str, set[tuple[str, str]]] = {}

    def register(self, session_id: str, gate: ApprovalGate) -> None:
        """注册已校验身份的控制通道；替换控制器同时废除旧临时授权。"""
        if self._gates.get(session_id) != gate:
            self._always_allowed.pop(session_id, None)
        self._gates[session_id] = gate

    def unregister(self, session_id: str, gate: ApprovalGate) -> None:
        """旧连接清理不能移除新连接的审批闸门。"""
        if self._gates.get(session_id) == gate:
            self.clear_session(session_id)

    def gate_for(self, session_id: str) -> ApprovalGate | None:
        """取得当前会话的审批等待接口。"""
        return self._gates.get(session_id)

    def allow_always(self, session_id: str, tool_name: str, scope: str = "") -> None:
        """授权仅对同一用户、工作区、模式及运行生命周期有效。"""
        self._always_allowed.setdefault(session_id, set()).add((tool_name, scope))

    def is_always_allowed(self, session_id: str, tool_name: str, scope: str = "") -> bool:
        """普通授权不能替代平台 ACL、升档或业务确认。"""
        return (tool_name, scope) in self._always_allowed.get(session_id, set())

    def clear_session(self, session_id: str) -> None:
        """关闭运行时，清除控制通道和会话临时授权。"""
        self._gates.pop(session_id, None)
        self._always_allowed.pop(session_id, None)


broker = ApprovalBroker()


async def request_approval(
    *, session_id: str, log: Any, turn: int, step: int, attempt_id: str,
    call: dict[str, Any], emit: Callable, approval_broker: ApprovalBroker = broker,
    scope: str = "", owner_user_id: str = "", timeout_seconds: float = 300,
) -> str:
    """先提交审批事实再等待；gate 必须联动 pending_confirm 并校验 nonce/身份。

    主 Agent 将 log.append 的 approval 事实与写卡/清卡放入同一事务。
    gate 接收完整 identity，只有经过授权的 WS 回执才能 resolve 对应 Future。
    """
    approval_id = str(uuid5(NAMESPACE_URL, f"approval:{session_id}:{turn}:{attempt_id}:{call['id']}"))
    base = {
        "id": approval_id, "approval_id": approval_id, "interaction_id": approval_id,
        "session_id": session_id, "turn": turn, "turn_id": f"{session_id}:{turn}",
        "step": step, "attempt_id": attempt_id,
        "call_id": call["id"], "toolName": call["name"], "name": call["name"],
        "owner_user_id": owner_user_id or getattr(log, "actor_id", ""),
        "scope": scope, "nonce": uuid4().hex, "expires_at": time.time() + timeout_seconds,
    }

    def record(kind: str, payload: dict[str, Any]) -> None:
        """只向上层发布已经提交的事实；WS 自行生成安全投影。"""
        event = log.append(kind, {**base, **payload})
        emit({"kind": kind.replace("/", "_"), "seq": event["seq"],
              "event_ts": event["ts"], "record_type": event["type"], **base, **payload})

    if approval_broker.is_always_allowed(session_id, call["name"], scope):
        record("approval/decided", {"outcome": "always", "source_outcome": "allowed-always", "implicit": True})
        return "always"
    record("approval/asked", {"args": call["args"]})
    gate = approval_broker.gate_for(session_id)
    try:
        decision = "unavailable" if gate is None else await asyncio.wait_for(
            gate({**base, "name": call["name"], "args": call["args"]}), timeout_seconds
        )
    except TimeoutError:
        decision = "timeout"
    except asyncio.CancelledError:
        record("approval/decided", {"outcome": "cancelled", "source_outcome": "cancelled"})
        raise
    outcomes = {
        "allow": ("allow", "allowed"), "always": ("always", "allowed-always"),
        "deny": ("deny", "denied"), "timeout": ("expired", "timed_out"),
        "unavailable": ("deny", "unavailable"),
    }
    outcome, source_outcome = outcomes.get(decision, ("deny", "invalid"))
    record("approval/decided", {"outcome": outcome, "source_outcome": source_outcome})
    if decision == "always":
        approval_broker.allow_always(session_id, call["name"], scope)
    return decision
