"""错误码枚举单测（M0 空跑，不依赖数据库）。"""

from app.errors import _CODE_STATUS, ErrorCode


def test_error_code_enum_has_ten_codes():
    # PRD 5.5 / API V1.0 §1.3 定义的十个错误码
    expected = {
        "UNAUTHORIZED",
        "VALIDATION",
        "NOT_FOUND",
        "BUDGET_EXCEEDED",
        "CONCURRENCY",
        "WHITELIST",
        "NEED_APPROVAL",
        "UPSTREAM",
        "TIMEOUT",
        "INTERNAL",
    }
    assert {c.value for c in ErrorCode} == expected


def test_error_code_default_status_mapping():
    assert _CODE_STATUS[ErrorCode.UNAUTHORIZED] == 403
    assert _CODE_STATUS[ErrorCode.VALIDATION] == 400
    assert _CODE_STATUS[ErrorCode.NOT_FOUND] == 404
    assert _CODE_STATUS[ErrorCode.BUDGET_EXCEEDED] == 409
    assert _CODE_STATUS[ErrorCode.CONCURRENCY] == 409
    assert _CODE_STATUS[ErrorCode.WHITELIST] == 403
    assert _CODE_STATUS[ErrorCode.NEED_APPROVAL] == 403
    assert _CODE_STATUS[ErrorCode.UPSTREAM] == 502
    assert _CODE_STATUS[ErrorCode.TIMEOUT] == 504
    assert _CODE_STATUS[ErrorCode.INTERNAL] == 500
