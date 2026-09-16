"""PostgreSQL 子 Agent 事实日志：每个 run 独立排序，不写主会话历史。"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

from sqlalchemy import select

from app.errors import AppError, ErrorCode
from app.models import AgentRun, AgentRunEvent


class SubagentLog:
    """实现 ``RuntimeLog`` 的最小持久端口，序号由 AgentRun 行锁分配。"""

    def __init__(self, session_id: str, run_id: str, session_factory, *, actor_id: str):
        """身份均由协调器创建；run 必须已经持久化且属于当前会话协作。"""
        if not session_id or not run_id or not actor_id:
            raise ValueError("子运行日志身份不能为空")
        self.session_id = session_id
        self.run_id = run_id
        self.session_factory = session_factory
        self.actor_id: str | None = actor_id
        self.command_context: dict[str, Any] = {}

    def append(self, kind: str, data: dict[str, Any], **metadata: Any) -> dict[str, Any]:
        """在同一事务内分配 seq 并提交事实，logical_key 重放必须内容一致。"""
        value = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
        logical_key = metadata.get("logical_key")
        with self.session_factory() as db:
            run = db.execute(
                select(AgentRun).where(AgentRun.id == self.run_id).with_for_update()
            ).scalar_one_or_none()
            if run is None:
                raise AppError(ErrorCode.NOT_FOUND, "专家运行不存在")
            if logical_key:
                previous = db.execute(
                    select(AgentRunEvent).where(
                        AgentRunEvent.run_id == self.run_id,
                        AgentRunEvent.logical_key == logical_key,
                    )
                ).scalar_one_or_none()
                if previous is not None:
                    if previous.envelope.get("data") != value:
                        raise AppError(ErrorCode.CONCURRENCY, "同一子运行事件身份对应不同数据")
                    return deepcopy(previous.envelope)
            seq = int(run.next_seq or 0)
            event = {
                "schema_version": 2,
                "event_version": 1,
                "event_id": f"subevt-{self.run_id}-{seq}",
                "session_id": self.session_id,
                "run_id": self.run_id,
                "seq": seq,
                "ts": time.time(),
                "type": kind,
                "durability": "committed",
                "correlation": {
                    key: value[key]
                    for key in ("turn", "step", "attempt_id", "call_id")
                    if key in value
                },
                "data": value,
                "extensions": {},
            }
            if "turn" in value:
                event["correlation"]["turn_id"] = f"{self.session_id}:{self.run_id}:{value['turn']}"
            run.next_seq = seq + 1
            db.add(
                AgentRunEvent(
                    run_id=self.run_id,
                    seq=seq,
                    type=kind,
                    logical_key=logical_key,
                    envelope=event,
                )
            )
            db.commit()
            return deepcopy(event)

    def read(self) -> list[dict[str, Any]]:
        """按子运行序号返回独立历史。"""
        with self.session_factory() as db:
            rows = db.execute(
                select(AgentRunEvent.envelope)
                .where(AgentRunEvent.run_id == self.run_id)
                .order_by(AgentRunEvent.seq)
            ).scalars().all()
            return deepcopy(list(rows))
