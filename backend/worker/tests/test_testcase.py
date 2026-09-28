"""用例 Worker 的来源权限、文件格式、模型数据和确认超时回归。"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openpyxl import Workbook
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app import main, task_state, testcase
from app.models import (
    CaseItem,
    CaseSet,
    ProtocolProfile,
    Setting,
    StoredFile,
    Task,
    TaskEvent,
    utcnow,
)
def _file(path, filename="requirements.xlsx", kind="xlsx", owner="owner"):
    """构造与真实上传相同的无扩展名存储文件元数据。"""
    return StoredFile(
        id="file", filename=filename, kind=kind, storage_path=str(path),
        size_bytes=1, sha256="0" * 64, uploaded_by=owner,
    )


def test_excel_source_reads_uuid_storage_path(worker_db_factory, tmp_path):
    """Excel 类型取自上传元数据，不能把 UUID 文件路径当 UTF-8 文本。"""
    path = tmp_path / "upload-uuid"
    workbook = Workbook()
    workbook.active.append(["支付", "订单创建成功"])
    workbook.save(path)
    workbook.close()
    with worker_db_factory() as db:
        db.add(_file(path))
        db.commit()
        assert testcase._read_source(db, {"file_id": "file"}, "owner") == "支付 订单创建成功"
        with pytest.raises(FileNotFoundError):
            testcase._read_source(db, {"file_id": "file"}, "other")


def test_worker_rechecks_source_owner_before_any_provider_call(worker_db_factory, tmp_path, monkeypatch):
    """历史任务或排队后撤权也不能把他人文件发送给模型。"""
    path = tmp_path / "source"
    path.write_text("另一个成员的需求", encoding="utf-8")
    with worker_db_factory() as db:
        db.add(_file(path, filename="requirements.txt", kind="txt"))
        db.add(Task(
            id="task", kind="testcase", status="running", created_by="other",
            config={"case_source": {"file_id": "file"}},
        ))
        db.commit()
    provider = Mock(side_effect=AssertionError("不得调用供应商"))
    monkeypatch.setattr(testcase, "call_protocol", provider)
    testcase.run_testcase("task")
    provider.assert_not_called()
    with worker_db_factory() as db:
        assert db.get(Task, "task").status == "failed"
        assert db.get(Task, "task").result["error_code"] == "VALIDATION"
        assert db.query(CaseSet).count() == 0


def test_generated_items_protect_identity_and_mark_missing_expected(worker_db_factory):
    """模型的系统字段不进入 extras；合法扩展列保留，缺预期行正确标为待补全。"""
    rows = testcase._to_case_items("set", [{
        "id": "model-id", "case_set_id": "foreign-set", "mapped": True,
        "pending_complete": False, "extras": {"id": "nested-id"},
        "sort_order": 100, "created_at": "bad", "updated_at": "bad",
        "name": "正常登录", "strategy": "正向", "priority": "HX", "负责人": "QA",
    }])
    with worker_db_factory() as db:
        db.add(CaseSet(id="set", name="生成集"))
        db.add_all(rows)
        db.commit()
        item = db.query(CaseItem).one()
        assert item.id != "model-id" and item.case_set_id == "set"
        assert item.mapped is False and item.pending_complete is True
        assert item.sort_order == 0
        assert item.extras == {"负责人": "QA"}


@pytest.mark.parametrize("interruption", [None, "cancelled", "expired"])
def test_generation_persists_only_while_task_still_owns_execution(
    worker_db_factory, monkeypatch, interruption,
):
    """真实执行入口正确落库；模型等待期间取消或回收租约时丢弃迟到结果。"""
    with worker_db_factory() as db:
        db.add(ProtocolProfile(
            id="profile", name="local", protocol="openai_chat",
            base_url="https://example.test", model="local",
        ))
        db.add(Setting(key="agent_profile_id", value="profile"))
        db.add(Task(
            id="task", kind="testcase", status="running", created_by="owner",
            claimed_by_worker_id="worker", claim_expires_at=utcnow() + timedelta(minutes=1),
            config={"case_source": {"text": "登录需求"}},
        ))
        db.commit()
    monkeypatch.setattr(testcase, "profile_connection", lambda *_args, **_kwargs: (
        "https://example.test", "local", "local-test-placeholder",
    ))
    monkeypatch.setattr(testcase, "read_profile_env", lambda _id: SimpleNamespace(full_url=False))

    def complete_model(**_kwargs):
        """在模型返回边界模拟另一事务的取消或租约回收，不发网络请求。"""
        if interruption:
            with worker_db_factory() as db:
                task = db.get(Task, "task")
                if interruption == "cancelled":
                    task.status = "cancelled"
                else:
                    task.claim_expires_at = utcnow() - timedelta(seconds=1)
                db.commit()
                if interruption == "expired":
                    assert task_state.recover_expired_task_leases(db) == 1
        return SimpleNamespace(text='[{"id":"model-id","name":"登录成功","strategy":"正向","priority":"HX","expected":"进入工作台"}]')

    monkeypatch.setattr(testcase, "call_protocol", complete_model)
    testcase.run_testcase("task")
    with worker_db_factory() as db:
        task = db.get(Task, "task")
        if interruption:
            assert task.status == ("cancelled" if interruption == "cancelled" else "failed")
            assert db.query(CaseSet).count() == 0
            assert db.query(CaseItem).count() == 0
        else:
            assert task.status == "awaiting_case_confirm"
            case_set = db.query(CaseSet).one()
            item = db.query(CaseItem).one()
            assert case_set.created_by == "owner" and case_set.task_id == task.id
            assert case_set.expires_at is not None and case_set.generated_count == 1
            assert item.id != "model-id" and item.pending_complete is False


def test_generation_honors_snapshot_count_and_weights(worker_db_factory, monkeypatch):
    """对话任务的数量与策略快照同时进入提示词和落库后处理。"""
    with worker_db_factory() as db:
        db.add(ProtocolProfile(
            id="profile", name="local", protocol="openai_chat",
            base_url="https://example.test", model="local",
        ))
        db.add(Setting(key="agent_profile_id", value="profile"))
        db.add(Task(
            id="task", kind="testcase", status="running", created_by="owner",
            claimed_by_worker_id="worker", claim_expires_at=utcnow() + timedelta(minutes=1),
            config={"case_source": {"text": "登录需求"}, "max_count": 2,
                    "strategy_weights": {"positive": 100}},
        ))
        db.commit()
    monkeypatch.setattr(testcase, "profile_connection", lambda *_args, **_kwargs: (
        "https://example.test", "local", "local-test-placeholder",
    ))
    monkeypatch.setattr(testcase, "read_profile_env", lambda _id: SimpleNamespace(full_url=False))
    calls = []

    def complete_model(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=(
            '[{"name":"正向1","strategy":"正向","priority":"HX","expected":"成功"},'
            '{"name":"正向2","strategy":"正向","priority":"HX","expected":"成功"},'
            '{"name":"反向","strategy":"反向","priority":"YC","expected":"拒绝"},'
            '{"name":"未知","strategy":"其他","priority":"FHX","expected":"结果"}]'
        ))

    monkeypatch.setattr(testcase, "call_protocol", complete_model)
    testcase.run_testcase("task")
    assert len(calls) == 1
    assert "不超过 2 条" in calls[0]["messages"][0]["content"]
    assert "正向 100%" in calls[0]["messages"][0]["content"]
    with worker_db_factory() as db:
        assert db.get(Task, "task").status == "awaiting_case_confirm"
        assert [row.name for row in db.query(CaseItem).order_by(CaseItem.sort_order)] == ["正向1", "正向2"]


@pytest.mark.parametrize("max_count,budget", [(45, 8192), (80, 16384)])
def test_generation_keeps_short_model_output_with_target_quota(
    worker_db_factory, monkeypatch, max_count, budget,
):
    """模型少于目标条数时按目标配比裁剪，不对实际返回数再次缩额。"""
    with worker_db_factory() as db:
        db.add(ProtocolProfile(
            id="profile", name="local", protocol="openai_chat",
            base_url="https://example.test", model="local",
        ))
        db.add(Setting(key="agent_profile_id", value="profile"))
        db.add(Task(
            id="task", kind="testcase", status="running", created_by="owner",
            claimed_by_worker_id="worker", claim_expires_at=utcnow() + timedelta(minutes=1),
            config={"case_source": {"text": "登录需求"}, "max_count": max_count},
        ))
        db.commit()
    monkeypatch.setattr(testcase, "profile_connection", lambda *_args, **_kwargs: (
        "https://example.test", "local", "local-test-placeholder",
    ))
    monkeypatch.setattr(testcase, "read_profile_env", lambda _id: SimpleNamespace(full_url=False))
    calls = []

    def fake_model(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=(
            '[{"name":"正向1","strategy":"正向","priority":"HX","expected":"成功"},'
            '{"name":"正向2","strategy":"正向","priority":"HX","expected":"成功"},'
            '{"name":"正向3","strategy":"正向","priority":"HX","expected":"成功"}]'
        ))

    monkeypatch.setattr(testcase, "call_protocol", fake_model)

    testcase.run_testcase("task")
    assert calls[0]["max_tokens"] == budget
    with worker_db_factory() as db:
        assert db.get(Task, "task").status == "awaiting_case_confirm"
        assert [row.name for row in db.query(CaseItem).order_by(CaseItem.sort_order)] == [
            "正向1", "正向2", "正向3",
        ]


def test_confirmation_expiry_only_cancels_eligible_locked_rows(worker_db_factory, monkeypatch):
    """只取消截止且未确认的行；既有成功任务不误报超时，锁顺序为用例集后任务。"""
    now = utcnow()
    with worker_db_factory() as db:
        db.add_all([
            Task(id="waiting", kind="testcase", status="awaiting_case_confirm", created_by="owner"),
            Task(id="finished", kind="testcase", status="succeeded", created_by="owner"),
            CaseSet(id="expired", task_id="waiting", name="过期", expires_at=now - timedelta(seconds=1)),
            CaseSet(id="confirmed", task_id="finished", name="确认", status="confirmed", expires_at=now - timedelta(seconds=1)),
            CaseSet(id="future", name="有效", expires_at=now + timedelta(hours=1)),
        ])
        db.commit()
    pushes = []
    monkeypatch.setattr(main, "push_ws", lambda *args, **kwargs: pushes.append((args, kwargs)))
    with worker_db_factory() as db:
        statements = []

        def record_statement(execution):
            """按 PostgreSQL 方言记录查询锁语义，SQLite 仅验证实际持久化状态。"""
            statements.append(str(execution.statement.compile(dialect=postgresql.dialect())))

        event.listen(db, "do_orm_execute", record_statement)
        assert main._expire_stale_case_confirmations(db) == 1
        assert db.get(CaseSet, "expired").status == "cancelled"
        assert db.get(Task, "waiting").status == "cancelled"
        assert db.get(CaseSet, "confirmed").status == "confirmed"
        assert db.get(Task, "finished").status == "succeeded"
        assert db.get(CaseSet, "future").status == "generated"
        assert db.query(TaskEvent).count() == 1
        locks = [sql for sql in statements if "FOR UPDATE" in sql]
        assert "case_sets" in locks[0] and "SKIP LOCKED" in locks[0]
        assert "tasks" in locks[1]
    assert pushes == []  # 无会话任务无需广播，更不能为 finished 误报取消。
