"""新会话固定 AgentLoop，历史 legacy 与旧 WS 入口继续隔离。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models import Session, User
from app.routers import sessions, ws
from app.schemas import SessionCreate
from tests import test_loop_store_pg as fixtures

pg_case = fixtures.pg_case


def test_new_session_is_v2_and_client_cannot_create_legacy(pg_case):
    """新会话固定 AgentLoop，客户端也不能请求创建 legacy。"""
    with pg_case.factory() as db:
        user = db.get(User, pg_case.user_id)
        with pytest.raises(ValidationError):
            SessionCreate(engine_version="legacy")
        result = sessions.create_session(SessionCreate(title="new client"), db, user)
        pg_case.session_ids.append(result["id"])
        assert result["engine_version"] == "agent_loop_v2"
        assert db.scalar(select(func.count()).select_from(Session).where(Session.user_id == user.id)) == 1


def test_new_session_engine_is_persisted_and_listed(pg_case):
    """新会话的真实引擎持久化，列表返回可供前端选择正确协议的值。"""
    with pg_case.factory() as db:
        user = db.get(User, pg_case.user_id)
        result = sessions.create_session(SessionCreate(), db, user)
        pg_case.session_ids.append(result["id"])
        assert result["engine_version"] == "agent_loop_v2"
        listed = sessions.list_sessions(db, user)["items"]
        assert next(item for item in listed if item["id"] == result["id"])["engine_version"] == "agent_loop_v2"


@pytest.mark.asyncio
async def test_legacy_socket_rejects_v2_before_accept_or_model(pg_case, monkeypatch):
    """旧入口不能给新会话回放旧事件或启动第二套循环。"""
    sid = pg_case.session()
    monkeypatch.setattr(ws, "SessionLocal", pg_case.factory)
    monkeypatch.setattr(ws, "_consume_ws_ticket", lambda db, ticket: db.get(User, pg_case.user_id))
    socket = SimpleNamespace(query_params={"ticket": "test-ticket", "session_id": sid},
                             close=AsyncMock(), accept=AsyncMock())
    await ws.agent_websocket(socket)
    socket.accept.assert_not_awaited()
    assert socket.close.await_args.kwargs["code"] == 4400


@pytest.mark.asyncio
async def test_legacy_socket_cannot_implicitly_create_new_session(monkeypatch):
    """旧 WS 缺会话标识时 fail-closed，不能绕过新会话固定引擎。"""
    db = SimpleNamespace(close=Mock(), rollback=Mock())
    monkeypatch.setattr(ws, "SessionLocal", lambda: db)
    monkeypatch.setattr(ws, "_consume_ws_ticket", lambda db, ticket: SimpleNamespace(id="member"))
    socket = SimpleNamespace(query_params={"ticket": "test-ticket"}, close=AsyncMock(), accept=AsyncMock())
    await ws.agent_websocket(socket)
    socket.accept.assert_not_awaited()
    assert socket.close.await_args.kwargs["code"] == 4400
    # 替身没有 add/commit；若旧代码尝试隐式创建会话，此测试会立即失败。
    db.rollback.assert_not_called()
    db.close.assert_called_once()
