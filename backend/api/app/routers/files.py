"""本地文件卷的上传与元数据查询接口。"""

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import StoredFile, User, uuid_str
from ..schemas import FileOut

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".md",
    ".txt",
    ".html",
    ".pdf",
    ".json",
    ".yaml",
    ".yml",
    ".xlsx",
    ".xls",
    ".csv",
    ".jsonl",
    ".doc",
    ".docx",
    ".wav",
    ".mp3",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}


def _validate_filename(filename: str | None) -> str:
    """校验上传文件名和 V1.0 扩展名白名单。"""
    name = Path(filename or "").name
    if not name or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise AppError(ErrorCode.VALIDATION, "不支持的文件类型")
    return name


@router.post("", response_model=FileOut, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """校验后将文件写入本地卷，并持久化 SHA-256 元数据。"""
    filename = _validate_filename(file.filename)
    content = await file.read(MAX_FILE_BYTES + 1)
    if not content:
        raise AppError(ErrorCode.VALIDATION, "文件不能为空")
    if len(content) > MAX_FILE_BYTES:
        raise AppError(ErrorCode.VALIDATION, "单文件不能超过 20MB")

    file_id = uuid_str()
    storage_dir = Path(settings.data_dir) / "files"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / file_id
    storage_path.write_bytes(content)
    stored = StoredFile(
        id=file_id,
        filename=filename,
        content_type=file.content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(storage_path),
        kind=Path(filename).suffix.lower().lstrip("."),
        uploaded_by=user.id,
    )
    db.add(stored)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        raise
    db.refresh(stored)
    return stored


@router.get("/{file_id}", response_model=FileOut)
def get_file_metadata(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回文件元数据，不返回二进制内容或内部存储路径。"""
    stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not stored:
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    return stored


@router.get("/{file_id}/content")
def get_file_content(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """登录后下载或在线播放文件二进制；不回内部存储路径。"""
    stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not stored:
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    path = Path(stored.storage_path)
    if not path.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    media = stored.content_type or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=stored.filename,
        content_disposition_type="inline",
    )
