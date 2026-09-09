"""本地文件卷的上传与元数据查询接口。"""

import hashlib
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import Message, StoredFile, User, uuid_str
from ..models import Session as AgentSession
from ..schemas import FileOut

logger = logging.getLogger("ai-eval.api.files")

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_FILE_BYTES = 20 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
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
        logger.warning("附件上传拒绝：类型不支持 filename=%r", filename)
        raise AppError(ErrorCode.VALIDATION, "不支持的文件类型")
    return name


async def _save_upload_stream(file: UploadFile, temporary_path: Path) -> tuple[int, str]:
    """分块写入上传文件并同步计算哈希，避免把 20MB 附件一次性留在 API 内存。"""
    total_bytes = 0
    digest = hashlib.sha256()
    with temporary_path.open("xb") as target:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            total_bytes += len(chunk)
            if total_bytes > MAX_FILE_BYTES:
                raise AppError(ErrorCode.VALIDATION, "单文件不能超过 20MB")
            target.write(chunk)
            digest.update(chunk)
        target.flush()
        os.fsync(target.fileno())
    return total_bytes, digest.hexdigest()


@router.post("", response_model=FileOut, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """校验后分块写入本地卷，并持久化 SHA-256 元数据。"""
    filename = _validate_filename(file.filename)
    file_id = uuid_str()
    storage_dir = Path(settings.data_dir) / "files"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / file_id
    temporary_path = storage_dir / f".{file_id}.uploading"
    try:
        size_bytes, sha256 = await _save_upload_stream(file, temporary_path)
        if not size_bytes:
            logger.warning("附件上传拒绝：空文件 filename=%r user=%s", filename, user.id)
            raise AppError(ErrorCode.VALIDATION, "文件不能为空")
        os.replace(temporary_path, storage_path)
    except AppError:
        temporary_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        logger.error("附件写入失败 filename=%r type=%s", filename, type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "附件保存失败") from exc
    stored = StoredFile(
        id=file_id,
        filename=filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        sha256=sha256,
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
    _require_file_access(db, user, stored)
    return stored


@router.get("/{file_id}/content")
def get_file_content(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """登录后下载或在线播放文件二进制；不回内部存储路径。"""
    stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    _require_file_access(db, user, stored)
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


def _require_file_access(db: Session, user: User, stored: StoredFile | None) -> None:
    """上传者或可见会话的附件读取者可访问；仅知道 UUID 不构成授权。"""
    if stored is None:
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    if stored.uploaded_by == user.id:
        return
    # 同时兼容旧字符串引用和 AttachmentView 对象引用，仅遍历可见会话消息。
    refs = db.query(Message.attachments).join(AgentSession, AgentSession.id == Message.session_id).filter(
        AgentSession.deleted_at.is_(None),
        or_(AgentSession.user_id == user.id, AgentSession.visibility == "team"),
    )
    for (attachments,) in refs:
        if any((item if isinstance(item, str) else item.get("file_id") if isinstance(item, dict) else None) == stored.id for item in attachments or []):
            return
    raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
