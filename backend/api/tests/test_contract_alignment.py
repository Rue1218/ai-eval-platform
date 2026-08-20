"""已有模块契约对齐回归单测（API V1.5 审计修复项）。

覆盖：会话软删除路由、协议档 Agent 引用保护、任务全员只读口径、
TaskOut 顶层引用字段、activity-summary 时间边界解析。全部不依赖数据库。
"""

from datetime import UTC, datetime

import pytest

from app.errors import AppError, ErrorCode
from app.models import ProtocolProfile, Setting, Task, TaskEvent, User
from app.routers.profiles import delete_profile
from app.routers.sessions import router as sessions_router
from app.routers.tasks import _task_out, get_task, task_summary
from app.routers.users import _parse_bound


class _RichQuery:
    """吞掉任意链式调用并返回预置结果的多用途查询桩。"""

    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def group_by(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def count(self):
        return len(self._result) if isinstance(self._result, list) else 1

    def first(self):
        return self._result

    def all(self):
        return self._result if isinstance(self._result, list) else [self._result]


class _RichFakeDb:
    """按查询模型分发预置结果的会话桩；未登记的模型回退 default。"""

    def __init__(self, results: dict | None = None, default=None):
        self._results = results or {}
        self._default = default
        self.deleted: list = []
        self.added: list = []

    def query(self, *args, **kwargs):
        key = args[0] if args else None
        return _RichQuery(self._results.get(key, self._default))

    def delete(self, obj, *args, **kwargs):
        self.deleted.append(obj)

    def add(self, obj, *args, **kwargs):
        self.added.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, *args, **kwargs):
        pass


class _FakeRequest:
    """仅提供 client 属性探测的最小请求桩。"""

    client = None


def _user(uid: str = "u-1", username: str = "alice") -> User:
    """构造不落库的成员 ORM 实例。"""
    return User(id=uid, username=username)


def _task(creator: str) -> Task:
    """构造带 config 快照的任务 ORM 实例。"""
    return Task(
        id="t-1",
        kind="benchmark",
        status="queued",
        created_by=creator,
        config={"kind": "benchmark", "dataset_id": "ds-1"},
        progress={"done": 0, "total": 0, "message": "任务已入队"},
        result={},
    )


# ─── 1. V1.5 会话软删除接口（API §3.4） ───


def test_delete_session_endpoint_is_registered():
    """会话删除已升级为软删除契约，路由必须受登录依赖保护地注册。"""
    route = next(
        (item for item in sessions_router.routes if item.path == "/api/sessions/{session_id}"),
        None,
    )
    assert route is not None
    assert "DELETE" in route.methods


# ─── 2. 协议档删除的 Agent 引用保护（API §3.6） ───


def test_delete_profile_blocked_when_referenced_by_agent():
    # settings.agent_profile_id 指向该档：VALIDATION 拒绝且不产生删除
    profile = ProtocolProfile(id="p-1", name="agent-core")
    setting = Setting(key="agent_profile_id", value="p-1")
    db = _RichFakeDb({ProtocolProfile: profile, Setting: setting})
    with pytest.raises(AppError) as exc:
        delete_profile(profile_id="p-1", request=_FakeRequest(), db=db, user=_user())
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.deleted == []


def test_delete_profile_allowed_when_not_referenced():
    # 未被引用：正常删除并返回 ok
    profile = ProtocolProfile(id="p-1", name="old-model")
    db = _RichFakeDb({ProtocolProfile: profile, Setting: None})
    out = delete_profile(profile_id="p-1", request=_FakeRequest(), db=db, user=_user())
    assert out["ok"] is True
    assert db.deleted == [profile]


# ─── 3. 任务全员只读口径（API §3.10：列表/详情全员，取消/重跑限创建者） ───


def test_get_task_readable_by_any_member():
    # 非创建者也能读取任务详情与事件时间线（任务中心为团队共享视图）
    task = _task(creator="user-owner")
    db = _RichFakeDb({Task: task, TaskEvent: []})
    payload = get_task(task_id="t-1", db=db, user=_user("user-other"))
    assert payload["id"] == "t-1"
    assert payload["events"] == []
    assert payload["creator"] == "user-owner"


def test_task_summary_aggregates_all_members():
    # summary 不再按 created_by 过滤：直接聚合全员状态计数
    db = _RichFakeDb(default=[("succeeded", 3), ("queued", 1)])
    out = task_summary(db=db, user=_user())
    assert out["status_counts"]["succeeded"] == 3
    assert out["status_counts"]["queued"] == 1


def test_task_out_lifts_top_level_refs():
    # 列表 item 契约：dataset_id/kb_id 从 config 快照提升为顶层字段
    out = _task_out(_task(creator="u-1"))
    assert out["dataset_id"] == "ds-1"
    assert out["kb_id"] is None
    # creator 与 creator_id 并存输出，新旧消费端均兼容
    assert out["creator"] == "u-1"
    assert out["creator_id"] == "u-1"


# ─── 4. activity-summary 时间边界解析（API §3.3） ───


def test_parse_bound_default_passthrough():
    # 缺省值直接透传
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert _parse_bound(None, "from", now) is now
    assert _parse_bound("", "to", now) is now


def test_parse_bound_iso_and_z_suffix():
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    parsed = _parse_bound("2026-08-19T08:00:00Z", "from", now)
    assert parsed == datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    naive = _parse_bound("2026-08-19T08:00:00", "from", now)
    assert naive.tzinfo is UTC


def test_parse_bound_rejects_invalid():
    # 非法时间字符串统一按 VALIDATION 拒绝
    with pytest.raises(AppError) as exc:
        _parse_bound("not-a-time", "from", datetime.now(UTC))
    assert exc.value.code == ErrorCode.VALIDATION
