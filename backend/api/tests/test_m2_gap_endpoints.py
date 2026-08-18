"""M2/M4 补全端点的鉴权与解析逻辑单测（不依赖数据库连接）。

覆盖本次补全的契约端点：数据集上传、报告分享/基线、压测会签与时序、白名单治理。
未登录请求在依赖注入阶段即被 401 拒绝，不会触达数据库查询。
"""

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.main import app
from app.routers.datasets import _parse_upload_rows


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/datasets/ds-1/upload", None),
        ("POST", "/api/reports/r-1/share", {"expire_days": 7}),
        ("POST", "/api/reports/r-1/baseline", {"frozen": True}),
        ("POST", "/api/tasks/t-1/approve-stress", None),
        ("GET", "/api/tasks/t-1/stress-series", None),
        ("GET", "/api/admin/stress/whitelist", None),
        ("POST", "/api/admin/stress/whitelist", {"host": "10.0.0.8", "scope": "test"}),
        ("DELETE", "/api/admin/stress/whitelist/wl-01", None),
    ],
)
def test_gap_endpoints_require_auth(method: str, path: str, body: dict | None):
    # 未登录访问补全端点应统一返回 401 + UNAUTHORIZED
    client = TestClient(app)
    if method == "POST" and path.endswith("/upload"):
        resp = client.post(path, files={"file": ("a.jsonl", b'{"question":"q","reference":"r"}', "application/octet-stream")})
    else:
        resp = client.request(method, path, json=body)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_report_detail_rejects_anonymous_without_share():
    # 免登通道：未登录且未携带 share 令牌时，查库前直接 401 拒绝
    client = TestClient(app)
    resp = client.get("/api/reports/r-x")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_parse_upload_rows_jsonl():
    # JSONL：空行跳过，q/r 别名兼容，扩展列保留
    content = b'{"question":"q1","reference":"r1","tags":"a"}\n\n{"q":"q2","r":"r2"}\n'
    rows = _parse_upload_rows("ds.jsonl", content)
    assert len(rows) == 2
    assert rows[0]["tags"] == "a"


def test_parse_upload_rows_csv():
    content = "question,reference,context\n问1,答1,ctx\n问2,答2,\n".encode()
    rows = _parse_upload_rows("ds.csv", content)
    assert len(rows) == 2 and rows[0]["context"] == "ctx"


def test_parse_upload_rows_rejects_bad_structure():
    # 非法 JSON 行 / 缺列 CSV / 空文件 / 不支持的扩展名：整文件拒绝
    with pytest.raises(AppError) as e1:
        _parse_upload_rows("ds.jsonl", b"not-json\n")
    assert e1.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError):
        _parse_upload_rows("ds.csv", b"a,b\n1,2\n")
    with pytest.raises(AppError):
        _parse_upload_rows("ds.jsonl", b"\n\n")
    with pytest.raises(AppError):
        _parse_upload_rows("ds.txt", b"hello")
