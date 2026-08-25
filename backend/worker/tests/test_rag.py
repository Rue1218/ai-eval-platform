"""RAG 执行器（run_rag）单测：检索 → 指标 → EvalItem/Report 落库与终态。

通过 FakeDb 桩替换 SQLAlchemy 会话，monkeypatch ``shared.kb.retrieve``
返回固定检索结果，验证 hit_rate/mrr/recall 计算、样本落库与任务终态。
"""

from types import SimpleNamespace

from app import rag as rag_module
from app.models import EvalItem, GoldQa, GoldQaItem, KnowledgeBase, Report, Task


class _FakeQuery:
    """吞掉 filter/order_by 链并返回预置结果的最小查询桩。"""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    """覆盖 run_rag 所需的 query/add/commit/flush/rollback 的最小会话桩。"""

    def __init__(self, mappings):
        self._mappings = mappings
        self.added: list = []
        self.commit_calls = 0

    def query(self, model, *args, **kwargs):
        return _FakeQuery(self._mappings.get(model, []))

    def add(self, obj, *args, **kwargs):
        self.added.append(obj)

    def commit(self):
        self.commit_calls += 1

    def flush(self, *args, **kwargs):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _task(config: dict, status: str = "running") -> Task:
    """构造一个运行中的 rag 任务对象。"""
    return Task(
        id="t-rag",
        kind="rag",
        status=status,
        session_id=None,
        config=config,
        progress={},
        result={},
    )


def _kb() -> KnowledgeBase:
    return KnowledgeBase(id="kb-1", name="知识库", kind="lightrag", is_core=True)


def _qa() -> GoldQa:
    return GoldQa(id="qa-1", kb_id="kb-1", name="gold-qa", version=1, row_count=2)


def _items():
    return [
        GoldQaItem(gold_qa_id="qa-1", row_no=1, question="退款多久到账？", reference="1-3 个工作日", expected_doc_ids=["doc-a"]),
        GoldQaItem(gold_qa_id="qa-1", row_no=2, question="如何改绑手机号？", reference="", expected_doc_ids=["doc-z"]),
    ]


def _retrieve_mock(db, kb_id, query, mode="hybrid", k=5):
    """固定检索结果：第 1 行命中期望文档，第 2 行未命中。"""
    if "退款" in query:
        return [
            {"chunk_id": "doc-a#c01", "doc_id": "doc-a", "doc_name": "a.txt", "text": "退款 1-3 个工作日到账", "similarity": 0.9}
        ]
    return [{"chunk_id": "doc-x#c01", "doc_id": "doc-x", "doc_name": "x.txt", "text": "无关内容", "similarity": 0.5}]


def _setup(monkeypatch, config: dict | None = None):
    config = config or {
        "kb_id": "kb-1",
        "gold_qa_id": "qa-1",
        "rag_mode": ["hybrid"],
        "run": {"k": 5, "sample_size": 2},
    }
    task = _task(config)
    db = _FakeDb({Task: [task], KnowledgeBase: [_kb()], GoldQa: [_qa()], GoldQaItem: _items()})
    monkeypatch.setattr(rag_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(rag_module, "retrieve", _retrieve_mock)
    monkeypatch.setattr(rag_module, "push_ws", lambda *a, **k: None)
    monkeypatch.setattr(
        rag_module, "claim_running_task_for_terminal_write", lambda _db, _tid: task
    )
    return task, db


def test_run_rag_success_writes_samples_and_report(monkeypatch):
    task, db = _setup(monkeypatch)
    rag_module.run_rag(task.id)

    # 每行落一条 EvalItem
    samples = [o for o in db.added if isinstance(o, EvalItem)]
    assert len(samples) == 2
    row1 = next(s for s in samples if s.row_no == 1)
    row2 = next(s for s in samples if s.row_no == 2)
    assert row1.score == 1.0
    assert row2.score == 0.0
    assert row1.profile_id == "kb-1"

    report = next(o for o in db.added if isinstance(o, Report))
    assert report.kind == "rag"
    metrics = report.metrics
    assert metrics["hit_rate_at_k"] == 0.5
    assert metrics["mrr"] == 0.5
    assert metrics["recall_at_k"] == 0.5
    assert metrics["k"] == 5
    assert metrics["modes"] == ["hybrid"]
    assert "hit_denominator_note" in metrics
    assert "per_mode" in metrics

    assert task.status == "succeeded"
    assert task.report_id == report.id


def test_run_rag_handles_multiple_modes(monkeypatch):
    config = {
        "kb_id": "kb-1",
        "gold_qa_id": "qa-1",
        "rag_mode": ["naive", "hybrid"],
        "run": {"k": 5},
    }
    task, db = _setup(monkeypatch, config)
    rag_module.run_rag(task.id)

    samples = [o for o in db.added if isinstance(o, EvalItem)]
    assert len(samples) == 2  # 行级一条，mode 明细折叠进 output
    report = next(o for o in db.added if isinstance(o, Report))
    assert report.metrics["modes"] == ["naive", "hybrid"]
    assert set(report.metrics["per_mode"].keys()) == {"naive", "hybrid"}
    assert task.status == "succeeded"


def test_run_rag_fails_when_kb_missing(monkeypatch):
    task, db = _setup(monkeypatch)
    db._mappings[KnowledgeBase] = []  # 知识库不存在
    rag_module.run_rag(task.id)

    assert task.status == "failed"
    assert task.result.get("error_code") == "VALIDATION"
    assert not [o for o in db.added if isinstance(o, Report)]


def test_run_rag_fails_when_qa_empty(monkeypatch):
    task, db = _setup(monkeypatch)
    db._mappings[GoldQaItem] = []
    rag_module.run_rag(task.id)

    assert task.status == "failed"
    assert task.result.get("error_code") == "VALIDATION"
