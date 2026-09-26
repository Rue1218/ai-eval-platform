"""用例工作台缺陷回归：真实 ORM 覆盖来源权限、终态、映射及保存契约。"""

import asyncio
import json
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from openpyxl import Workbook
from sqlalchemy import JSON, BigInteger, Integer, MetaData, create_engine, event, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from app.errors import AppError, ErrorCode
from app.models import (
    AuditLog,
    CaseItem,
    CaseSet,
    Dataset,
    DatasetRow,
    StoredFile,
    Task,
    User,
    utcnow,
)
from app.routers import cases as routes
from app.schemas import (
    CaseAiFillIn,
    CaseAiGenerateIn,
    CaseCancelIn,
    CaseConfirmIn,
    CaseMapIn,
    CasesPayload,
)


@pytest.fixture
def cases_db():
    """仅在内存库复制相关 DDL；保留 ORM 行为与事务，适配 JSONB 和自增主键。"""
    metadata = MetaData()
    pending = [model.__table__ for model in (
        User, CaseSet, CaseItem, Task, Dataset, DatasetRow, StoredFile, AuditLog,
    )]
    while pending:
        table = pending.pop()
        if table.name in metadata.tables:
            continue
        copied = table.to_metadata(metadata)
        for column in copied.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif column.primary_key and isinstance(column.type, BigInteger):
                column.type = Integer()
        for index in copied.indexes:
            condition = index.dialect_options["postgresql"].get("where")
            if condition is not None:
                index.dialect_options["sqlite"]["where"] = condition
        pending.extend(foreign.column.table for foreign in table.foreign_keys)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    try:
        with sessionmaker(engine, autoflush=False)() as db:
            db.add_all([
                User(id="owner", username="owner", password_hash="fake"),
                User(id="other", username="other", password_hash="fake"),
            ])
            db.add(CaseSet(id="set", name="需求用例", created_by="owner"))
            db.commit()
            yield db
    finally:
        engine.dispose()


def _actor():
    """返回固定测试成员，避免读取真实登录状态。"""
    return SimpleNamespace(id="owner")


def _request():
    """审计测试不包含真实客户端地址。"""
    return SimpleNamespace(client=None)


def _add_case(db, case_id="case", **overrides):
    """插入真实用例，缺省为完整的核心正向样本。"""
    row = CaseItem(**{
        "id": case_id, "case_set_id": "set", "name": case_id,
        "strategy": "正向", "priority": "HX", "expected": "成功", **overrides,
    })
    db.add(row)
    db.commit()
    return row


def _waiting_task(db, *, expired=False):
    """为用例集关联待确认任务，期限可由测试切换。"""
    task = Task(id="task", kind="testcase", created_by="owner", status="awaiting_case_confirm")
    db.add(task)
    case_set = db.get(CaseSet, "set")
    case_set.task_id = task.id
    case_set.expires_at = utcnow() + timedelta(hours=-1 if expired else 1)
    db.commit()
    return task


def test_generate_rejects_foreign_file_before_model_call(cases_db, monkeypatch):
    """知道私有附件 ID 不能代替来源授权，拒绝时不读取磁盘也不调用模型。"""
    cases_db.add(StoredFile(
        id="private", filename="private.txt", uploaded_by="other", size_bytes=1,
        sha256="0" * 64, storage_path="/must-not-read/private.bin",
    ))
    cases_db.commit()
    monkeypatch.setattr(routes, "call_agent_model", lambda *a, **k: pytest.fail("不能调用模型"))
    with pytest.raises(AppError) as error:
        routes.ai_generate_cases(CaseAiGenerateIn(source_doc_id="private"), cases_db, _actor())
    assert error.value.code == ErrorCode.UNAUTHORIZED


def test_excel_source_uses_original_filename_with_bin_storage(cases_db, tmp_path):
    """模拟上传器的 UUID.bin 存储，抽取的素材必须是单元格正文。"""
    workbook = Workbook()
    workbook.active.append(["登录需求", "错误密码应拒绝登录"])
    buffer = BytesIO()
    workbook.save(buffer)
    path = tmp_path / "upload.bin"
    path.write_bytes(buffer.getvalue())
    cases_db.add(StoredFile(
        id="excel", filename="需求.xlsx", kind="xlsx", uploaded_by="owner",
        size_bytes=path.stat().st_size, sha256="0" * 64, storage_path=str(path),
    ))
    cases_db.commit()
    assert routes._read_stored_file_text(cases_db, "excel", "owner") == "登录需求 错误密码应拒绝登录"


def test_generate_applies_requested_weights_and_drops_model_identity(cases_db, monkeypatch):
    """全正向配置贯穿提示词和后处理，供应商不能指定待保存行的身份。"""
    output = [{"name": str(index), "strategy": "正向", "id": "forged"} for index in range(20)]
    output.append({"name": "多余反向", "strategy": "反向"})
    monkeypatch.setattr(routes, "call_agent_model", lambda *a, **k: SimpleNamespace(text=json.dumps(output)))
    result = routes.ai_generate_cases(
        CaseAiGenerateIn(source_text="需求", max_count=20, strategy_weights={"positive": 100}),
        cases_db, _actor(),
    )
    assert len(result["items"]) == 20
    assert all("id" not in item and item["strategy"] == "正向" for item in result["items"])


def test_save_reorders_ids_recomputes_checks_and_ignores_workflow_fields(cases_db):
    """保存响应跟随提交顺序，真实状态不受客户端平铺的保留字段覆盖。"""
    _add_case(cases_db, "first", sort_order=0)
    _add_case(cases_db, "second", sort_order=1, strategy="反向")
    result = routes.save_cases("set", CasesPayload(cases=[
        {"id": "second", "name": "反向", "strategy": "反向", "priority": "YC", "expected": "拒绝"},
        {"id": "first", "name": "正向", "strategy": "正向", "priority": "HX", "expected": "成功", "mapped": True},
        {"name": "新增", "strategy": "边界", "priority": "BJ", "expected": "边界有效"},
    ]), cases_db, _actor())
    assert [item["id"] for item in result["items"][:2]] == ["second", "first"]
    assert result["items"][2]["id"] not in {"first", "second"}
    assert result["items"][1]["mapped"] is False
    assert result["checks"] == []
    assert cases_db.get(CaseSet, "set").generated_count == 3


def test_save_empty_clears_last_row_and_recomputes_checks(cases_db):
    """最后一条用例删除后允许提交空快照，计数和检查项跟随真实剩余行。"""
    _add_case(cases_db)
    result = routes.save_cases("set", CasesPayload(cases=[]), cases_db, _actor())
    assert result["items"] == [] and result["total"] == 0
    assert cases_db.get(CaseSet, "set").generated_count == 0
    assert len(result["checks"]) == 2


@pytest.mark.parametrize("status", ["confirmed", "cancelled"])
def test_terminal_set_rejects_save_and_ai_fill(cases_db, monkeypatch, status):
    """终态同时约束持久编辑和模型补全，不能继续消耗供应商调用。"""
    _add_case(cases_db)
    cases_db.get(CaseSet, "set").status = status
    cases_db.commit()
    monkeypatch.setattr(routes, "call_agent_model", lambda *a, **k: pytest.fail("终态不能补全"))
    with pytest.raises(AppError):
        routes.save_cases("set", CasesPayload(cases=[]), cases_db, _actor())
    with pytest.raises(AppError):
        routes.ai_fill_cases("set", CaseAiFillIn(case_ids=["case"]), cases_db, _actor())
    assert cases_db.query(CaseItem).count() == 1


def test_confirm_expired_set_cannot_succeed_before_expiry_scan(cases_db):
    """扫描尚未执行也不能确认过期结果，任务和用例集不会出现相反终态。"""
    task = _waiting_task(cases_db, expired=True)
    with pytest.raises(AppError) as error:
        routes.confirm_case_set("set", CaseConfirmIn(ok=True), _request(), cases_db, _actor())
    assert error.value.code == ErrorCode.VALIDATION
    assert cases_db.get(CaseSet, "set").status == "generated"
    assert task.status == "awaiting_case_confirm"


def test_confirm_uses_case_set_then_task_locks_and_refreshes_stale_state(cases_db):
    """记录真实 ORM 的加锁语句，并证明旧 identity map 不会覆盖已取消的任务。"""
    task = _waiting_task(cases_db)
    _ = task.status
    cases_db.execute(update(Task).where(Task.id == task.id).values(status="cancelled"),
                     execution_options={"synchronize_session": False})
    locked = []

    def record_lock(execute_state):
        """SQLite 不模拟 PostgreSQL 行锁，仅检查生产查询锁序及刷新行为。"""
        statement = execute_state.statement
        if execute_state.is_select and statement._for_update_arg is not None:
            locked.append(statement.column_descriptions[0]["entity"])

    event.listen(cases_db, "do_orm_execute", record_lock)
    with pytest.raises(AppError):
        routes.confirm_case_set("set", CaseConfirmIn(ok=True), _request(), cases_db, _actor())
    assert locked == [CaseSet, Task]
    assert task.status == "cancelled"
    assert cases_db.get(CaseSet, "set").status == "generated"


def test_cancel_transitions_case_set_and_task_together(cases_db):
    """废弃用例与关联任务在同一事务产生一致终态。"""
    task = _waiting_task(cases_db)
    result = routes.cancel_case_set("set", CaseCancelIn(), _request(), cases_db, _actor())
    assert result.status == task.status == "cancelled"
    assert task.finished_at is not None


def test_map_rejects_published_dataset_without_legacy_write(cases_db):
    """存在正式版本时映射必须显式拒绝，不能写入评测读取不到的 legacy 行。"""
    _add_case(cases_db)
    cases_db.add(Dataset(id="dataset", name="已发布", active_version_id="version"))
    cases_db.commit()
    with pytest.raises(AppError) as error:
        routes.map_cases("set", CaseMapIn(target="dataset", target_id="dataset", case_ids=["case"]),
                         _request(), cases_db, _actor())
    assert "受控导入" in error.value.message
    assert cases_db.query(DatasetRow).count() == 0
    assert cases_db.get(CaseItem, "case").mapped is False


def test_map_legacy_is_idempotent_for_duplicate_ids_and_retry(cases_db):
    """重复点击、网络重试和重复勾选均只写一份映射。"""
    _add_case(cases_db)
    cases_db.add(Dataset(id="dataset", name="旧数据集"))
    cases_db.commit()
    body = CaseMapIn(target="dataset", target_id="dataset", case_ids=["case", "case"])
    first = routes.map_cases("set", body, _request(), cases_db, _actor())
    second = routes.map_cases("set", body, _request(), cases_db, _actor())
    assert first["mapped_count"] == 1 and second["mapped_count"] == 0
    assert cases_db.query(DatasetRow).count() == 1
    assert cases_db.get(Dataset, "dataset").row_count == 1


def test_ai_fill_rejects_foreign_ids_and_filters_metadata(cases_db, monkeypatch):
    """模型不能改写已有名称、非请求字段或流程状态，只能补当前行缺失内容。"""
    _add_case(cases_db, expected="")
    output = [
        {"id": "foreign", "expected": "越权"},
        {"id": "case", "name": "改写原名", "expected": "补全", "mapped": True, "case_set_id": "foreign"},
    ]
    monkeypatch.setattr(routes, "call_agent_model", lambda *a, **k: SimpleNamespace(text=json.dumps(output)))
    result = routes.ai_fill_cases("set", CaseAiFillIn(case_ids=["case"]), cases_db, _actor())
    assert result == {"items": [{"id": "case", "expected": "补全"}]}
    assert cases_db.get(CaseItem, "case").expected == ""


def test_ai_fill_rechecks_state_after_model_returns(cases_db, monkeypatch):
    """生成候选期间发生废弃，返回前再次拒绝，行锁不会覆盖整个供应商调用。"""
    _add_case(cases_db, expected="")

    def model_returns_after_cancel(*args, **kwargs):
        """模拟外部终态已提交，不调用真实供应商。"""
        cases_db.get(CaseSet, "set").status = "cancelled"
        cases_db.commit()
        return SimpleNamespace(text='[{"id":"case","expected":"不能继续编辑"}]')

    monkeypatch.setattr(routes, "call_agent_model", model_returns_after_cancel)
    with pytest.raises(AppError) as error:
        routes.ai_fill_cases("set", CaseAiFillIn(case_ids=["case"]), cases_db, _actor())
    assert error.value.code == ErrorCode.VALIDATION
    assert cases_db.get(CaseItem, "case").expected == ""


def test_append_import_recomputes_checks_from_entire_set(cases_db):
    """追加反向用例后检查项同时包含已有核心正向，不能仅检查本次导入批次。"""
    _add_case(cases_db)
    workbook = Workbook()
    workbook.active.append(["策略", "优先级", "模块", "用例名称", "预期结果"])
    workbook.active.append(["反向", "YC", "登录", "错误密码", "拒绝登录"])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    result = asyncio.run(routes.import_case_set(
        "set", _request(), UploadFile(file=buffer, filename="补充.xlsx"), "append", cases_db, _actor(),
    ))
    assert result["generated_count"] == 2
    assert result["checks"] == []


@pytest.mark.parametrize("mode", ["append", "replace"])
@pytest.mark.parametrize("identity", ["new", "existing", "foreign"])
def test_import_repeated_ids_update_one_local_row(cases_db, mode, identity):
    """批内重复编号沿用同编号更新语义，跨集编号只重建一个本集副本。"""
    if identity == "existing":
        _add_case(cases_db, "repeated")
    elif identity == "foreign":
        cases_db.add(CaseSet(id="other-set", name="其他集合", created_by="other"))
        _add_case(cases_db, "repeated", case_set_id="other-set", name="其他集合原文")
    workbook = Workbook()
    workbook.active.append(["用例编号", "用例名称", "预期结果"])
    workbook.active.append(["repeated", "第一次", "首次预期"])
    workbook.active.append(["repeated", "最后一次", "最终预期"])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    result = asyncio.run(routes.import_case_set(
        "set", _request(), UploadFile(file=buffer, filename="重复编号.xlsx"), mode, cases_db, _actor(),
    ))
    rows = cases_db.query(CaseItem).filter(CaseItem.case_set_id == "set").all()
    assert result["generated_count"] == len(rows) == 1
    assert rows[0].name == "最后一次" and rows[0].expected == "最终预期"
    if identity == "foreign":
        assert rows[0].id != "repeated"
        assert cases_db.get(CaseItem, "repeated").name == "其他集合原文"
