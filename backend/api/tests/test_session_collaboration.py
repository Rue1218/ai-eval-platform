"""团队共享会话的权限、软删除和瞬态正文流回归测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agent.harness import handle_confirm_ack
from app.errors import ErrorCode
from app.models import AuditLog, Task, User
from app.models import Session as AgentSession
from app.routers.sessions import delete_session
from app.session_access import can_access_session
from app.session_connections import SessionConnectionHub


class _Query:
    """按 ORM 模型回传预置对象的最小链式查询桩。"""

    def __init__(self, result: object | None) -> None:
        self.result = result

    def filter(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def with_for_update(self) -> _Query:
        return self

    def first(self) -> object | None:
        return self.result

    def all(self) -> list[object]:
        return []


class _Db:
    """覆盖会话删除与确认卡路径的无数据库事务桩。"""

    def __init__(self, results: dict[object, object | None]) -> None:
        self.results = results
        self.added: list[object] = []
        self.commit_calls = 0

    def query(self, model: object) -> _Query:
        return _Query(self.results.get(model))

    def add(self, row: object) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.commit_calls += 1

    def flush(self) -> None:
        return None

    def refresh(self, _row: object) -> None:
        return None


class _State:
    """模拟连接自己的事件游标和发送锁。"""

    def __init__(self, cursor: int) -> None:
        self.cursor = cursor
        self.lock = asyncio.Lock()


class _Socket:
    """收集 Hub 发送帧与关闭码的最小 WebSocket 桩。"""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.close_codes: list[int] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)

    async def close(self, code: int) -> None:
        self.close_codes.append(code)


def _session(
    *,
    owner_id: str = "u-owner",
    visibility: str = "private",
    deleted_at: datetime | None = None,
) -> AgentSession:
    """构造最小会话 ORM 对象以验证共享策略。"""
    return AgentSession(
        id="s-1",
        user_id=owner_id,
        title="团队会话",
        visibility=visibility,
        deleted_at=deleted_at,
    )


def test_session_visibility_policy_keeps_private_default_and_team_collaboration():
    """private 仅 owner，team 对团队成员开放，软删除对所有成员隐藏。"""
    private = _session()
    team = _session(visibility="team")
    deleted = _session(visibility="team", deleted_at=datetime.now(UTC))

    assert can_access_session(private, "u-owner") is True
    assert can_access_session(private, "u-peer") is False
    assert can_access_session(team, "u-peer") is True
    assert can_access_session(deleted, "u-owner") is False


def test_team_chunk_hub_uses_each_receiver_cursor_and_revokes_non_owner():
    """正文 chunk 广播不复用发起者游标，收回共享会关闭协作者连接。"""
    hub = SessionConnectionHub()
    owner_socket, peer_socket = _Socket(), _Socket()
    owner_state, peer_state = _State(7), _State(31)
    hub.register("owner-conn", "s-1", "u-owner", owner_socket, owner_state)
    hub.register("peer-conn", "s-1", "u-peer", peer_socket, peer_state)

    asyncio.run(
        hub.broadcast_chunk(
            "s-1",
            lambda cursor: {"event": "thought", "event_id": cursor, "payload": {"stream": "chunk"}},
        )
    )

    assert owner_socket.frames == [
        {"event": "thought", "event_id": 7, "payload": {"stream": "chunk"}}
    ]
    assert peer_socket.frames == [
        {"event": "thought", "event_id": 31, "payload": {"stream": "chunk"}}
    ]

    asyncio.run(hub.close_non_owner("s-1", "u-owner"))
    assert owner_socket.close_codes == []
    assert peer_socket.close_codes == [4404]


def test_confirm_ack_rejects_collaborator_and_preserves_card():
    """团队协作者不能确认、拒绝或清空另一个成员创建的确认卡。"""
    session = _session(visibility="team")
    session.pending_confirm = {"kind": "benchmark"}
    session.pending_confirm_author_id = "u-owner"
    db = _Db({AgentSession: session})
    events: list[tuple[str, dict]] = []

    async def emit(event: str, payload: dict, **_kwargs: object) -> int:
        events.append((event, payload))
        return 1

    asyncio.run(
        handle_confirm_ack(
            db,
            session=session,
            user=User(id="u-peer", username="peer"),
            ok=False,
            patch=None,
            emit=emit,
        )
    )

    assert session.pending_confirm == {"kind": "benchmark"}
    assert session.pending_confirm_author_id == "u-owner"
    assert db.commit_calls == 0
    assert events == [
        (
            "error",
            {
                "code": ErrorCode.UNAUTHORIZED.value,
                "message": "仅确认卡发起人可以确认或取消该任务",
            },
        )
    ]


def test_delete_session_soft_deletes_without_removing_audit_assets():
    """空闲 owner 会话删除只写 deleted_at 和审计，不删除关联业务资产。"""
    session = _session()
    db = _Db({AgentSession: session, Task: None})
    owner = User(id="u-owner", username="owner")

    response = asyncio.run(delete_session("s-1", db=db, user=owner))

    assert response.status_code == 204
    assert session.deleted_at is not None
    assert db.commit_calls == 1
    assert any(isinstance(row, AuditLog) and row.action == "session_delete" for row in db.added)
