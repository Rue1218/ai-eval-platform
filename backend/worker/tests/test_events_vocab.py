"""dsh 改进 #4：worker push_ws 写库带词汇版本断言（D5 测试清单）。"""

from __future__ import annotations

from shared.event_vocab import EVENT_VERSION

from app.events import push_ws


def test_push_ws_injects_event_version_and_does_not_mutate_caller_payload(monkeypatch) -> None:
    """写库 payload 内嵌版本保留字段；调用方 payload 不被污染（拷贝语义）。"""
    added: list[object] = []

    class _Col:
        """SQLAlchemy 列占位：order_by(WsEvent.event_id.desc()) 可求值。"""

        def desc(self):
            return self

        def __eq__(self, _other):
            return True

    class _FakeWsEvent:
        # push_ws 事件号查询会访问类属性 WsEvent.session_id / WsEvent.event_id
        # （SQLAlchemy 列）；提供类级占位以免 AttributeError，查询链对取值不解析。
        session_id = _Col()
        event_id = _Col()

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr("app.events.WsEvent", _FakeWsEvent)

    class _Query:
        """query 链替身：第 1 次查询（会话行锁）返回存在；第 2 次（事件号）无历史。"""

        def __init__(self, step: int) -> None:
            self._step = step

        def filter(self, *_args):
            return self

        def with_for_update(self):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return ("s-1",) if self._step == 1 else None

    class _Db:
        def __init__(self) -> None:
            self._calls = 0

        def query(self, *_args):
            self._calls += 1
            return _Query(self._calls)

        def add(self, row) -> None:
            added.append(row)

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.events.SessionLocal", _Db)

    payload = {"percent": 10, "message": "进度"}
    push_ws("s-1", "progress", payload, task_id="t-1")

    assert len(added) == 1
    stored = added[0].kwargs
    assert stored["session_id"] == "s-1"
    assert stored["event_id"] == 1
    assert stored["event"] == "progress"
    assert stored["payload"]["percent"] == 10
    assert stored["payload"]["event_version"] == EVENT_VERSION
    # 调用方 payload 不得被注入保留字段
    assert "event_version" not in payload


def test_push_ws_skips_without_session() -> None:
    """无会话 ID 时静默跳过，不触碰数据库。"""
    assert push_ws(None, "progress", {"percent": 1}) is None
