"""文件扩展名白名单单测，覆盖 Agent 附件支持的图片与文档格式。"""

import pytest

from app.errors import AppError, ErrorCode
from app.routers.files import _validate_filename


@pytest.mark.parametrize("filename", ["photo.jpg", "photo.PNG", "readme.md", "brief.pdf", "spec.doc", "spec.docx", "cases.xlsx"])
def test_validate_filename_accepts_agent_attachment_formats(filename: str) -> None:
    """Agent 上传入口应接受图片、Markdown、PDF、Word 与 Excel 文件。"""
    assert _validate_filename(filename) == filename.split("/")[-1]


def test_validate_filename_rejects_unsupported_format() -> None:
    """不在契约白名单内的扩展名必须统一返回 VALIDATION。"""
    with pytest.raises(AppError) as exc_info:
        _validate_filename("payload.exe")
    assert exc_info.value.code == ErrorCode.VALIDATION
