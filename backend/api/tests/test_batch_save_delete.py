"""批量保存的「当前视图替换」删除语义单测（save_cases / save_dataset_rows）。

前端批量删除是「本地删 → 保存修改」，保存端必须删除载荷中未包含的现有
行/用例，否则删除永远不落库。此单测用 FakeDb 验证该删除行为。
"""

from types import SimpleNamespace

from app.models import CaseItem, CaseSet, Dataset, DatasetRow
from app.routers.cases import save_cases
from app.routers.datasets import save_dataset_rows
from app.schemas import CasesPayload, RowsPayload


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

    def count(self):
        return len(self._rows)


class _FakeDb:
    """覆盖批量保存所需 query/delete/add/commit/flush 的最小会话桩。"""

    def __init__(self, rows_by_model):
        self._rows = rows_by_model
        self.deleted: list = []
        self.added: list = []
        self.commit_calls = 0

    def query(self, model, *args, **kwargs):
        return _FakeQuery(self._rows.get(model, []))

    def delete(self, obj):
        self.deleted.append(obj)
        for key, rows in self._rows.items():
            if obj in rows:
                rows.remove(obj)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_calls += 1

    def flush(self, *args, **kwargs):
        pass

    def refresh(self, *args, **kwargs):
        pass


def _case(cid: str) -> CaseItem:
    return CaseItem(
        id=cid, case_set_id="s-1", strategy="正向", priority="FHX",
        module="m", name=f"用例 {cid}", expected="e",
    )


def test_save_cases_deletes_omitted_cases():
    """载荷未包含的现有用例应被删除（前端批量删除的落库依据）。"""
    case_set = CaseSet(id="s-1", name="集", status="generated", generated_count=2, column_schema=[], checks=[])
    db = _FakeDb({CaseSet: [case_set], CaseItem: [_case("c-1"), _case("c-2")]})
    payload = CasesPayload(cases=[{
        "id": "c-1", "strategy": "正向", "priority": "FHX", "module": "m", "name": "用例 c-1", "expected": "e",
    }])
    result = save_cases("s-1", payload, db, SimpleNamespace(id="u-1"))
    assert [d.id for d in db.deleted] == ["c-2"]
    assert result["total"] == 1
    assert [c["id"] for c in result["items"]] == ["c-1"]


def test_save_cases_keeps_all_when_full_list_sent():
    """全量载荷时不应删除任何行。"""
    case_set = CaseSet(id="s-1", name="集", status="generated", generated_count=2, column_schema=[], checks=[])
    db = _FakeDb({CaseSet: [case_set], CaseItem: [_case("c-1"), _case("c-2")]})
    payload = CasesPayload(cases=[
        {"id": "c-1", "strategy": "正向", "priority": "FHX", "module": "m", "name": "用例 c-1", "expected": "e"},
        {"id": "c-2", "strategy": "正向", "priority": "FHX", "module": "m", "name": "用例 c-2", "expected": "e"},
    ])
    result = save_cases("s-1", payload, db, SimpleNamespace(id="u-1"))
    assert db.deleted == []
    assert result["total"] == 2


def test_save_dataset_rows_deletes_omitted_rows():
    """载荷未包含的现有数据行应被删除（数据集表格批量删除的落库依据）。"""
    dataset = Dataset(id="d-1", name="集", version=1, row_count=2, pending_complete_count=0, column_schema=[])
    row1 = DatasetRow(id="r-1", dataset_id="d-1", row_no=1, question="q1", reference="r1")
    row2 = DatasetRow(id="r-2", dataset_id="d-1", row_no=2, question="q2", reference="r2")
    db = _FakeDb({Dataset: [dataset], DatasetRow: [row1, row2]})
    payload = RowsPayload(rows=[{"row_no": 1, "q": "q1", "r": "r1"}])
    result = save_dataset_rows("d-1", payload, db, SimpleNamespace(id="u-1"))
    assert [d.row_no for d in db.deleted] == [2]
    assert result["total"] == 1
