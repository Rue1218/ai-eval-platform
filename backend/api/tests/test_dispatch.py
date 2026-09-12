"""调度内核路由单测（不依赖数据库连接）。

心跳超时判定为纯函数单测；未登录请求在依赖注入阶段即被 401 拒绝。
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.dispatch import HEARTBEAT_TIMEOUT, _effective_state


def _worker(state: str, heartbeat: datetime | None = None) -> SimpleNamespace:
    """构造仅含心跳判定所需字段的节点替身。"""
    return SimpleNamespace(state=state, last_heartbeat_at=heartbeat)


class TestEffectiveState:
    """心跳超时的 busy/idle 节点按离线对待，显式治理状态原样保留。"""

    def test_fresh_idle_stays_idle(self) -> None:
        assert _effective_state(_worker("idle", datetime.now(UTC))) == "idle"

    def test_fresh_busy_stays_busy(self) -> None:
        assert _effective_state(_worker("busy", datetime.now(UTC))) == "busy"

    def test_stale_busy_becomes_offline(self) -> None:
        stale = datetime.now(UTC) - HEARTBEAT_TIMEOUT - timedelta(seconds=1)
        assert _effective_state(_worker("busy", stale)) == "offline"

    def test_missing_heartbeat_is_offline(self) -> None:
        assert _effective_state(_worker("idle", None)) == "offline"

    def test_naive_heartbeat_treated_as_utc(self) -> None:
        """无时区心跳按 UTC 解释（兼容数据库返回 naive datetime）。"""
        naive = datetime.now(UTC).replace(tzinfo=None)
        assert _effective_state(_worker("idle", naive)) == "idle"

    def test_explicit_states_preserved(self) -> None:
        """draining/offline 为显式治理状态，不参与心跳超时降级。"""
        for state in ("draining", "offline"):
            assert _effective_state(_worker(state, datetime.now(UTC))) == state


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/dispatch/overview", None),
        ("GET", "/api/dispatch/workers", None),
        ("POST", "/api/dispatch/workers", {"id": "w-1", "name": "节点一"}),
        ("PUT", "/api/dispatch/workers/w-1", {"state": "draining"}),
        ("PUT", "/api/dispatch/config", {"strategy": "负载均衡"}),
        ("GET", "/api/dispatch/events", None),
    ],
)
def test_dispatch_endpoints_require_auth(method: str, path: str, body) -> None:
    """未登录一律 401 UNAUTHORIZED。"""
    client = TestClient(app)
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"
