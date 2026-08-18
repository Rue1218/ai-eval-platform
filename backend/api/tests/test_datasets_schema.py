"""数据集工作台扩展的 schema 与鉴权单测（不依赖数据库连接）。

未携带登录 Cookie 的请求在依赖注入阶段即被 401 拒绝，
不会触达 SQLAlchemy 查询，因此可在无数据库环境运行。
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import (
    AiGenerateIn,
    DatasetCreate,
    DatasetRowIn,
    DatasetUpdate,
    FolderIn,
    RowsPayload,
)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/datasets", None),
        ("POST", "/api/datasets", {"name": "smoke-20"}),
        ("GET", "/api/datasets/ds-1", None),
        ("PUT", "/api/datasets/ds-1", {"name": "改名"}),
        ("DELETE", "/api/datasets/ds-1", None),
        ("GET", "/api/datasets/ds-1/rows", None),
        ("GET", "/api/datasets/ds-1/rows?pending_complete=true", None),
        ("PUT", "/api/datasets/ds-1/rows", {"rows": [{"row_no": 1, "q": "问", "r": "答"}]}),
        (
            "POST",
            "/api/datasets/ai-generate",
            {"dataset_id": "ds-1", "mode": "scene", "instruction": "支付高频问答"},
        ),
        ("GET", "/api/dataset-folders", None),
        ("POST", "/api/dataset-folders", {"name": "目录"}),
        ("PUT", "/api/dataset-folders/f-1", {"name": "改名"}),
        ("DELETE", "/api/dataset-folders/f-1", None),
    ],
)
def test_dataset_endpoints_require_auth(method: str, path: str, body: dict | None):
    # 未登录访问数据集域全部端点应统一返回 401 + UNAUTHORIZED
    client = TestClient(app)
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_dataset_create_metric_default():
    # 创建数据集缺省评判口径为 contain
    body = DatasetCreate(name="smoke-20")
    assert body.metric == "contain"


def test_dataset_create_rejects_extra_field():
    # 输入模型继承 ApiModel，契约外字段一律拒绝
    with pytest.raises(ValidationError):
        DatasetCreate(name="x", unknown_field=1)


def test_dataset_update_partial_and_column_schema():
    body = DatasetUpdate(name="新名字")
    assert body.folder_id is None and body.column_schema is None
    cols = [{"key": "difficulty", "name": "难度", "type": "string", "sort_order": 1}]
    body2 = DatasetUpdate(column_schema=cols)
    assert body2.column_schema[0].key == "difficulty"
    assert body2.column_schema[0].required is False


def test_dataset_update_rejects_duplicate_column_key():
    cols = [
        {"key": "tags", "name": "标签", "type": "string"},
        {"key": "tags", "name": "重复", "type": "string"},
    ]
    with pytest.raises(ValidationError):
        DatasetUpdate(column_schema=cols)


def test_folder_in_name_optional_for_put():
    # PUT 目录可只改排序号；POST 时 name 必填由路由层校验
    body = FolderIn(sort_order=3)
    assert body.name is None and body.sort_order == 3


def test_row_in_accepts_extension_keys():
    # q/r/c 之外的扩展列 key 放行并进入 model_extra
    row = DatasetRowIn(row_no=1, q="如何修改结算账户？", r="进入设置...", tags="账户", difficulty="中等")
    assert (row.model_extra or {}).get("tags") == "账户"
    assert row.c is None


def test_rows_payload_rejects_duplicate_and_missing_row_no():
    with pytest.raises(ValidationError):
        RowsPayload(rows=[{"row_no": 1}, {"row_no": 1, "q": "x"}])
    with pytest.raises(ValidationError):
        RowsPayload(rows=[{"q": "缺 row_no"}])
    with pytest.raises(ValidationError):
        RowsPayload(rows=[])


def test_ai_generate_fill_missing_requires_rows():
    with pytest.raises(ValidationError):
        AiGenerateIn(dataset_id="ds-1", mode="fill_missing")
    ok = AiGenerateIn(dataset_id="ds-1", mode="fill_missing", rows=[{"row_no": 1, "q": ""}])
    assert ok.max_count == 10


def test_ai_generate_scene_requires_source():
    # 非 fill_missing 模式至少提供 instruction / source_text / seed 之一
    with pytest.raises(ValidationError):
        AiGenerateIn(dataset_id="ds-1", mode="scene")
    body = AiGenerateIn(dataset_id="ds-1", mode="doc", source_text="PRD 正文")
    assert body.mode == "doc"


def test_ai_generate_max_count_bounds():
    with pytest.raises(ValidationError):
        AiGenerateIn(dataset_id="ds-1", mode="seed", seed="s", max_count=0)
    with pytest.raises(ValidationError):
        AiGenerateIn(dataset_id="ds-1", mode="seed", seed="s", max_count=51)
