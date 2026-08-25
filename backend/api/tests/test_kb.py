"""知识库 / 黄金 QA 端点的鉴权与解析逻辑单测（不依赖数据库连接）。

未登录请求在依赖注入阶段即被 401 拒绝，不会触达数据库查询；
解析逻辑（黄金 QA 上传格式、文档文本解码、切块）为纯函数单测。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.kb import _decode_text, _parse_expected, _parse_gold_qa


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/kb"),
        ("POST", "/api/kb"),
        ("GET", "/api/kb/kb-1"),
        ("PUT", "/api/kb/kb-1"),
        ("DELETE", "/api/kb/kb-1"),
        ("GET", "/api/kb/kb-1/documents"),
        ("GET", "/api/kb/kb-1/documents/d-1/chunks"),
        ("DELETE", "/api/kb/kb-1/documents/d-1"),
        ("GET", "/api/kb/kb-1/gold-qa"),
        ("POST", "/api/kb/kb-1/query"),
    ],
)
def test_kb_endpoints_require_auth(method: str, path: str):
    client = TestClient(app)
    resp = client.request(method, path, json={"name": "x", "kind": "lightrag"} if method == "POST" else None)
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_kb_upload_endpoints_require_auth():
    client = TestClient(app)
    resp = client.post(
        "/api/kb/kb-1/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 401
    resp = client.post(
        "/api/kb/kb-1/gold-qa",
        files={"file": ("qa.jsonl", b'{"question":"q"}', "application/octet-stream")},
        data={"name": "qa"},
    )
    assert resp.status_code == 401


# ─── 黄金 QA 上传解析 ────────────────────────────────────────────────────


def test_parse_gold_qa_jsonl():
    content = (
        '{"question":"退款多久到账？","reference":"1-3 个工作日","expected_doc_ids":["d-01"]}\n'
        "\n"
        '{"question":"如何改绑手机号？","reference":"安全中心"}\n'
    ).encode()
    rows = _parse_gold_qa(content, "qa.jsonl")
    assert len(rows) == 2
    assert rows[0]["question"] == "退款多久到账？"
    assert rows[0]["expected_doc_ids"] == ["d-01"]
    assert rows[1]["expected_doc_ids"] == []


def test_parse_gold_qa_skips_lines_without_question():
    content = '{"reference":"仅参考"}\n{"question":"有效行","reference":"r"}\n'.encode()
    rows = _parse_gold_qa(content, "qa.jsonl")
    assert len(rows) == 1
    assert rows[0]["question"] == "有效行"


def test_parse_gold_qa_json_array():
    content = b'[{"question":"q1","expected_doc_ids":["d-1","d-2"]},{"question":"q2","reference":"r2"}]'
    rows = _parse_gold_qa(content, "qa.json")
    assert len(rows) == 2
    assert rows[0]["expected_doc_ids"] == ["d-1", "d-2"]


def test_parse_gold_qa_csv():
    content = "question,reference,expected_doc_ids\n问1,答1,\"['d-1','d-2']\"\n问2,答2,\n".encode()
    rows = _parse_gold_qa(content, "qa.csv")
    assert len(rows) == 2
    assert rows[0]["question"] == "问1"
    assert rows[0]["expected_doc_ids"] == ["d-1", "d-2"]


def test_parse_expected_normalizes_variants():
    assert _parse_expected(["a", 1]) == ["a", "1"]
    assert _parse_expected('["x","y"]') == ["x", "y"]
    assert _parse_expected("d-1;d-2") == ["d-1", "d-2"]
    assert _parse_expected(None) == []
    assert _parse_expected("") == []


def test_decode_text_tries_encodings():
    assert _decode_text("你好".encode()) == "你好"
    assert _decode_text("中文".encode("gbk")) == "中文"
    # 二进制内容（三套解码均失败）返回空串，文档状态落 failed
    assert _decode_text(bytes([0xC3, 0x28, 0xFF])) == ""


def test_chunk_text_basic():
    from shared.kb import chunk_text

    text = "a" * 1200
    chunks = chunk_text(text, chunk_size=512, overlap=64, doc_id="d-01")
    assert len(chunks) == 3
    assert chunks[0]["chunk_id"] == "d-01#c01"
    assert chunks[0]["tokens"] == 512
    assert "d-01#c02" in {c["chunk_id"] for c in chunks}


def test_chunk_text_single_short():
    from shared.kb import chunk_text

    chunks = chunk_text("短文本", doc_id="d")
    assert len(chunks) == 1 and chunks[0]["text"] == "短文本"
