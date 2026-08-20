"""用例工作台的 schema 与鉴权单测（不依赖数据库连接）。

未携带登录 Cookie 的请求在依赖注入阶段即被 401 拒绝，
不会触达 SQLAlchemy 查询，因此可在无数据库环境运行。
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import (
    CaseAiFillIn,
    CaseAiGenerateIn,
    CaseCancelIn,
    CaseConfirmIn,
    CaseIn,
    CaseMapIn,
    CaseSetCreate,
    CaseSetUpdate,
    CasesPayload,
)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/case-sets", None),
        ("POST", "/api/case-sets", {"name": "登录模块用例集"}),
        ("GET", "/api/case-sets/cs-1", None),
        ("PUT", "/api/case-sets/cs-1", {"name": "改名"}),
        (
            "PUT",
            "/api/case-sets/cs-1/cases",
            {"cases": [{"strategy": "正向", "priority": "P0", "name": "账密正确登录"}]},
        ),
        ("POST", "/api/case-sets/cs-1/confirm", {"ok": True}),
        ("POST", "/api/case-sets/cs-1/cancel", {"reason": "需求变更"}),
        (
            "POST",
            "/api/case-sets/cs-1/map",
            {"target": "dataset", "target_id": "ds-1", "case_ids": ["c-1"]},
        ),
        ("POST", "/api/case-sets/ai-generate", {"source_text": "PRD 正文"}),
        ("GET", "/api/case-sets/import-template", None),
        ("POST", "/api/case-sets/cs-1/import", None),
        ("POST", "/api/case-sets/cs-1/ai-fill", {"case_ids": ["c-1"]}),
        ("GET", "/api/case-sets/cs-1/export?fmt=xlsx", None),
        ("GET", "/api/case-folders", None),
        ("POST", "/api/case-folders", {"name": "目录"}),
        ("PUT", "/api/case-folders/f-1", {"name": "改名"}),
        ("DELETE", "/api/case-folders/f-1", None),
    ],
)
def test_case_endpoints_require_auth(method: str, path: str, body: dict | None):
    # 未登录访问用例域全部端点应统一返回 401 + UNAUTHORIZED
    client = TestClient(app)
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_case_set_create_rejects_extra_field():
    # 输入模型继承 ApiModel，契约外字段一律拒绝
    with pytest.raises(ValidationError):
        CaseSetCreate(name="x", unknown_field=1)


def test_case_set_rejects_duplicate_column_key():
    # 扩展列 key 重复时行内扩展值无法对应列定义，创建与更新均拦截
    cols = [
        {"key": "owner", "name": "负责人", "type": "string"},
        {"key": "owner", "name": "重复", "type": "string"},
    ]
    with pytest.raises(ValidationError):
        CaseSetCreate(name="x", column_schema=cols)
    with pytest.raises(ValidationError):
        CaseSetUpdate(column_schema=cols)


def test_case_in_accepts_extension_keys():
    # 固定字段之外的扩展列 key 放行并进入 model_extra
    case = CaseIn(strategy="正向", priority="P0", name="账密正确登录", owner="张三")
    assert (case.model_extra or {}).get("owner") == "张三"
    assert case.module == "" and case.precondition is None


def test_case_in_requires_core_fields():
    with pytest.raises(ValidationError):
        CaseIn(priority="P0", name="缺策略")
    with pytest.raises(ValidationError):
        CaseIn(strategy="正向", priority="P0", name="")


def test_cases_payload_rejects_duplicate_id_and_empty():
    case = {"strategy": "正向", "priority": "P0", "name": "用例"}
    with pytest.raises(ValidationError):
        CasesPayload(cases=[{**case, "id": "c-1"}, {**case, "id": "c-1"}])
    with pytest.raises(ValidationError):
        CasesPayload(cases=[])


def test_case_confirm_schema():
    # ok 必填；mapping_target 仅接受契约两种取值
    assert CaseConfirmIn(ok=True).mapping_target is None
    with pytest.raises(ValidationError):
        CaseConfirmIn()
    with pytest.raises(ValidationError):
        CaseConfirmIn(ok=True, mapping_target="excel")


def test_case_cancel_schema_default():
    assert CaseCancelIn().reason is None


def test_case_map_schema():
    body = CaseMapIn(target="dataset", target_id="ds-1", case_ids=["c-1"])
    assert body.target == "dataset"
    with pytest.raises(ValidationError):
        CaseMapIn(target="excel", target_id="ds-1", case_ids=["c-1"])
    with pytest.raises(ValidationError):
        CaseMapIn(target="dataset", target_id="ds-1", case_ids=[])


def test_ai_generate_requires_source():
    # source_doc_id 与 source_text 至少填一项
    with pytest.raises(ValidationError):
        CaseAiGenerateIn()
    ok = CaseAiGenerateIn(source_doc_id="file-1")
    assert ok.max_count == 45


def test_ai_generate_max_count_bounds():
    with pytest.raises(ValidationError):
        CaseAiGenerateIn(source_text="x", max_count=0)
    with pytest.raises(ValidationError):
        CaseAiGenerateIn(source_text="x", max_count=101)
    ok = CaseAiGenerateIn(source_text="x", max_count=100)
    assert ok.max_count == 100


def test_ai_generate_strategy_weights_passthrough():
    body = CaseAiGenerateIn(source_text="x", strategy_weights={"positive": 60, "negative": 40})
    assert body.strategy_weights["positive"] == 60


def test_ai_fill_requires_case_ids():
    with pytest.raises(ValidationError):
        CaseAiFillIn(case_ids=[])
    body = CaseAiFillIn(case_ids=["c-1"], fields=["expected"])
    assert body.fields == ["expected"]
