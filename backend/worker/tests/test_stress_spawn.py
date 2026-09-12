"""抽样夹紧与先评后压派生回归测试。"""

from app.models import Task
from app.sampling import SAMPLE_SIZE_CAP, clamp_sample_size
from app.stress_spawn import maybe_spawn_stress


class _Query:
    def __init__(self, result=None):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class _Db:
    def __init__(self, existing=None, fail_integrity=False):
        self._existing = existing
        self.fail_integrity = fail_integrity
        self.added = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def query(self, *_args):
        return _Query(self._existing)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        from sqlalchemy.exc import IntegrityError

        if self.fail_integrity:
            raise IntegrityError("stmt", {}, Exception("dup"))
        for obj in self.added:
            if isinstance(obj, Task) and not obj.id:
                obj.id = "child-1"

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def test_clamp_sample_size_caps_at_1000():
    assert clamp_sample_size(5000, 8000) == SAMPLE_SIZE_CAP
    assert clamp_sample_size(20, 8) == 8
    assert clamp_sample_size(None, 2000) == SAMPLE_SIZE_CAP
    assert clamp_sample_size(-1, 50) == 50
    assert clamp_sample_size(True, 50) == 50


def test_spawn_stress_skips_without_flag(monkeypatch):
    monkeypatch.setattr("app.stress_spawn.push_ws", lambda *a, **k: None)
    parent = Task(
        id="p1",
        kind="benchmark",
        status="succeeded",
        created_by="u1",
        session_id="s1",
        config={"with_stress": False},
    )
    assert maybe_spawn_stress(_Db(), parent) is None


def test_spawn_stress_creates_queued_child(monkeypatch):
    monkeypatch.setattr("app.stress_spawn.push_ws", lambda *a, **k: None)
    parent = Task(
        id="p1",
        kind="benchmark",
        status="succeeded",
        created_by="u1",
        session_id="s1",
        config={
            "with_stress": True,
            "stress": {"env": "test", "qps": 10, "duration_s": 60},
        },
    )
    db = _Db()
    child = maybe_spawn_stress(db, parent)
    assert child is not None
    assert child.kind == "stress"
    assert child.status == "queued"
    assert child.parent_task_id == "p1"
    assert child.config["need_approval"] is False
    assert db.commit_calls == 1


def test_spawn_stress_prod_requires_approval(monkeypatch):
    monkeypatch.setattr("app.stress_spawn.push_ws", lambda *a, **k: None)
    parent = Task(
        id="p1",
        kind="rag",
        status="succeeded",
        created_by="u1",
        session_id="s1",
        config={
            "with_stress": True,
            "stress": {"env": "prod", "qps": 10, "duration_s": 30},
        },
    )
    child = maybe_spawn_stress(_Db(), parent)
    assert child is not None
    assert child.config["need_approval"] is True
    assert "会签" in (child.progress or {}).get("message", "")
