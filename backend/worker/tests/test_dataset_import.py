"""受控数据集导入的纯函数回归测试。"""

import pytest

from app.dataset_import import (
    ImportFailure,
    _assert_safe_download_url,
    _is_selected,
    _normalise_row,
    _parse_artifact,
)


def test_jsonl_parser_and_frozen_filters_keep_matching_row():
    """JSONL 解析后必须按冻结 split/筛选条件保留且保留原始扩展字段。"""
    rows = _parse_artifact(
        b'{"split":"test","question":"Q","reference":"A","difficulty":"hard"}\n',
        "jsonl",
    )

    assert _is_selected(rows[0], {}, {"splits": ["test"], "filters": {"difficulty": "hard"}})
    row = _normalise_row(rows[0], 1, {"artifact_name": "unit"})
    assert row.question == "Q"
    assert row.reference == "A"
    assert row.extras == {"split": "test", "difficulty": "hard"}
    assert len(row.content_sha256) == 64


def test_invalid_jsonl_is_validation_failure():
    """来源格式损坏必须整体拒绝，不能静默跳过失真的样本。"""
    with pytest.raises(ImportFailure, match="合法 JSON") as exc_info:
        _parse_artifact(b"not-json\n", "jsonl")

    assert exc_info.value.code == "VALIDATION"


def test_private_source_address_is_rejected_before_download():
    """即使域名位于目录允许清单，私网 IP 也不得由 Worker 访问。"""
    with pytest.raises(ImportFailure, match="不安全网络地址") as exc_info:
        _assert_safe_download_url("https://127.0.0.1/artifact.jsonl", {"127.0.0.1"})

    assert exc_info.value.code == "VALIDATION"


def test_row_without_split_is_rejected_before_staging():
    """导入请求已选择 split 时，来源行不能以缺失 split 绕过冻结筛选。"""
    with pytest.raises(ImportFailure, match="缺少可验证的 split") as exc_info:
        _is_selected({"question": "Q", "reference": "A"}, {}, {"splits": ["test"]})

    assert exc_info.value.code == "VALIDATION"
