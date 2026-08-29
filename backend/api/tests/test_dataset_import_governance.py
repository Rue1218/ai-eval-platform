"""数据集目录导入治理的纯函数回归测试。"""

from types import SimpleNamespace

import pytest

from app.errors import AppError, ErrorCode
from app.routers.dataset_catalog import _validate_publish_rows, _validate_release_payload
from app.routers.datasets import _require_independent_staging_reviewer
from app.schemas import CatalogReleaseIn


def _release_body(**overrides: object) -> CatalogReleaseIn:
    """构造满足目录静态边界的最小 release 草稿。"""
    payload: dict[str, object] = {
        "display_version": "2026-08-29",
        "source_revision": "a" * 40,
        "manifest": {
            "artifacts": [
                {"url": "https://example.com/dataset.jsonl", "sha256": "b" * 64}
            ]
        },
        "license": {"status": "allowed"},
        "allowed_splits": ["test"],
        "filter_schema": {"version": 1, "fields": {}},
        "parser_id": "jsonl-qa-v1",
        "parser_version": "1.0.0",
        "task_family": "generation",
        "support_status": "supported",
    }
    payload.update(overrides)
    return CatalogReleaseIn(**payload)


def _staging_row(row_no: int, question: str, reference: str, split: str):
    """用最小对象模拟发布校验需要的 staging 行字段。"""
    return SimpleNamespace(
        row_no=row_no,
        question=question,
        reference=reference,
        provenance={"split": split},
    )


def test_submitter_cannot_edit_own_staging():
    """提报人与审核编辑人必须隔离。"""
    job = SimpleNamespace(created_by="member-a")
    with pytest.raises(AppError) as exc_info:
        _require_independent_staging_reviewer(job, SimpleNamespace(id="member-a"))

    assert exc_info.value.code == ErrorCode.VALIDATION
    _require_independent_staging_reviewer(job, SimpleNamespace(id="member-b"))


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([_staging_row(1, "Q", "", "test")], "缺少题目或参考答案"),
        (
            [_staging_row(1, "Q", "A", "test"), _staging_row(2, "Q", "A", "test")],
            "重复",
        ),
        (
            [_staging_row(1, "Q", "A", "dev"), _staging_row(2, "Q", "A", "test")],
            "跨 split 重复",
        ),
    ],
)
def test_publish_rejects_invalid_or_leaking_staging_rows(rows, expected: str):
    """正式版本不能接纳缺字段、同 split 重复或跨 split 泄漏的候选行。"""
    with pytest.raises(AppError, match=expected) as exc_info:
        _validate_publish_rows(rows)

    assert exc_info.value.code == ErrorCode.VALIDATION


def test_supported_release_requires_worker_registered_parser():
    """目录的 supported 标识必须与 Worker 可执行 parser 一致。"""
    entry = SimpleNamespace(allowed_domains=["example.com"])
    with pytest.raises(AppError, match="已注册解析器") as exc_info:
        _validate_release_payload(entry, _release_body(parser_id="unregistered-v1"))

    assert exc_info.value.code == ErrorCode.VALIDATION
