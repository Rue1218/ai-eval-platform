"""文件扩展名白名单单测，覆盖 Agent 附件支持的图片与文档格式。"""

import hashlib
from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from app.errors import AppError, ErrorCode
from app.routers.files import _save_upload_stream, _validate_filename


@pytest.mark.parametrize("filename", ["photo.jpg", "photo.PNG", "readme.md", "brief.pdf", "spec.doc", "spec.docx", "cases.xlsx"])
def test_validate_filename_accepts_agent_attachment_formats(filename: str) -> None:
    """Agent 上传入口应接受图片、Markdown、PDF、Word 与 Excel 文件。"""
    assert _validate_filename(filename) == filename.split("/")[-1]


def test_validate_filename_rejects_unsupported_format() -> None:
    """不在契约白名单内的扩展名必须统一返回 VALIDATION。"""
    with pytest.raises(AppError) as exc_info:
        _validate_filename("payload.exe")
    assert exc_info.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_save_upload_stream_writes_in_chunks_and_returns_digest(tmp_path) -> None:
    """上传入口分块落盘并返回准确大小与 SHA-256，不依赖一次性读取附件。"""
    content = b"agent attachment\n" * 200_000
    upload = UploadFile(filename="large.txt", file=BytesIO(content))
    target = tmp_path / ".uploading"

    size_bytes, sha256 = await _save_upload_stream(upload, target)

    assert size_bytes == len(content)
    assert sha256 == hashlib.sha256(content).hexdigest()
    assert target.read_bytes() == content
