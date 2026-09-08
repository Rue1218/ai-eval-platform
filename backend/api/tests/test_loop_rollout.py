"""真实会话创建、灰度开关与旧 WS 入口隔离。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.errors import AppError, ErrorCode
from app.models import Session, User
from app.routers import sessions, ws
from app.schemas import SessionCreate
from tests import test_loop_store_pg as fixtures

pg_case = fixtures.pg_case


def test_disabled_rollout_rejects_v2_before_write_and_allows_legacy(pg_case, monkeypatch):
    """灰度关闭不产生 v2 孤儿行，旧客户端仍能创建会话。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", False)
    with pg_case.factory() as db:
        user = db.get(User, pg_case.user_id)
        with pytest.raises(AppError) as caught:
            sessions.create_session(SessionCreate(engine_version="agent_loop_v2"), db, user)
        assert caught.value.code == ErrorCode.VALIDATION
        assert db.scalar(select(func.count()).select_from(Session).where(Session.user_id == user.id)) == 0
        result = sessions.create_session(SessionCreate(title="old client"), db, user)
        pg_case.session_ids.append(result["id"])
        assert result["engine_version"] == "legacy"


def test_enabled_rollout_returns_persisted_engine_in_create_and_list(pg_case, monkeypatch):
    """创建与列表均返回真实引擎，前端才可选择正确协议。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    with pg_case.factory() as db:
        user = db.get(User, pg_case.user_id)
        result = sessions.create_session(SessionCreate(engine_version="agent_loop_v2"), db, user)
        pg_case.session_ids.append(result["id"])
        assert result["engine_version"] == "agent_loop_v2"
        monkeypatch.setattr(settings, "agent_loop_enabled", False)
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
