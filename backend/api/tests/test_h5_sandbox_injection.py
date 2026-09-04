"""H5 完善（P0 审计缺口）：ws 回合文件沙箱与附件注入的单元验证。

覆盖：
1. ``_session_owned_file_ids`` 从会话 user 消息附件聚合 file_id（只收合法项）；
2. 查询异常降级为空集——注入属增强，任何失败不得阻断回合（旧短路语义）；
3. ``ensure_session_workspace`` 对非法会话标识拒绝（注入点容错依赖该校验）。
"""

from app.errors import AppError
from app.harness.execution.workspace import session_workspace_dir
from app.routers import ws


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Filter:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Query:
    def __init__(self, rows, fail: bool = False):
        self._rows = rows
        self._fail = fail

    def filter(self, *_args, **_kwargs):
        if self._fail:
            raise RuntimeError("query boom")
        return _Filter(self._rows)


class _FakeDb:
    def __init__(self, rows, fail: bool = False):
        self._rows = rows
        self._fail = fail

    def query(self, _model_attr):
        if self._fail:
            raise RuntimeError("db boom")
        return _Query(self._rows)


def test_owned_file_ids_aggregates_user_attachment_file_ids() -> None:
    rows = [
        ([{"file_id": "f-1"}, {"file_id": "f-2"}],),
        (None,),
        ([{"kind": "note", "file_id": "f-3"}],),
        ([{"file_id": 123}],),  # 非字符串忽略
        ([],),
    ]
    db = _FakeDb(rows)
    assert ws._session_owned_file_ids(db, "s-any") == frozenset({"f-1", "f-2", "f-3"})


def test_owned_file_ids_returns_empty_on_query_failure() -> None:
    """查询失败降级为空集：门禁短路（= 未注入语义），绝不阻断回合。"""
    db = _FakeDb([], fail=True)
    assert ws._session_owned_file_ids(db, "s-any") == frozenset()


def test_owned_file_ids_returns_empty_when_no_user_attachments() -> None:
    db = _FakeDb([])
    assert ws._session_owned_file_ids(db, "s-any") == frozenset()


def test_session_workspace_dir_rejects_non_uuid_identifiers() -> None:
    """注入点容错依赖该校验：桩标识（s-e2e 等）→ 拒绝，生产 UUID 恒可注入。"""
    try:
        session_workspace_dir("s-e2e")
    except AppError:
        pass
    else:
        raise AssertionError("非 UUID 会话标识应被工作区校验拒绝")
