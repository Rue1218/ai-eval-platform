"""用户工作区域路由（F1/G1，设计文档 A V0.4.1 §4）。

- 工作区 = 用户自管数据域：列表/创建/改名/注销（软删）/purge（真删）；
- 注销 = 软删（``deleted_at`` 标记），purge 事务内先显式解绑
  ``sessions.workspace_id`` 引用（FK RESTRICT 兜底，禁 SET NULL），再删行删目录；
- 目录浏览/建文件夹经 ``workspace_service`` 的路径安全单一实现（防穿越 +
  逐段 realpath 前缀重验 + 符号链接拒绝）；
- 全部写操作落 AuditLog；删除竞态守卫见 §4.2（workspace 行锁先行，S 列为
  UPDATE 行锁随后——全局锁序 workspace → sessions）。
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import Session as AgentSession
from ..models import User, Workspace
from ..workspace_service import (
    create_child_dir,
    create_workspace_file,
    delete_workspace_path,
    folder_summary,
    get_file_tree,
    list_dir_level,
    read_workspace_file,
    rename_workspace_path,
    resolve_scope_dir,
    resolve_scope_file,
    save_workspace_file_bytes,
    workspace_dir_for,
    write_workspace_file,
)
from ._common import write_audit

router = APIRouter(prefix="/api/workspaces", tags=["user-workspaces"])


class _NameBody(BaseModel):
    """工作区创建/改名请求（name 每属主活跃唯一）。"""

    name: str = Field(min_length=1, max_length=255)


class _FileBody(BaseModel):
    """新建文件夹请求：父目录相对路径（默认根）+ 单段目录名。"""

    path: str = Field(default="", max_length=1024)
    name: str = Field(min_length=1, max_length=255)


class _FileContentBody(BaseModel):
    """写回/更新文件内容请求。"""

    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(default="")


class _CreateFileBody(BaseModel):
    """新建单文件请求。"""

    path: str = Field(default="", max_length=1024)
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(default="")


class _RenamePathBody(BaseModel):
    """重命名文件或目录请求。"""

    path: str = Field(min_length=1, max_length=1024)
    new_name: str = Field(min_length=1, max_length=255)



def _owned_workspace(
    db: Session, user: User, workspace_id: str, *, require_active: bool = True
) -> Workspace:
    """按属主取工作区；非属主 403（UNAUTHORIZED），不存在 404。"""
    row = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "工作区不存在")
    if row.owner_id != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "无权访问该工作区")
    if require_active and row.deleted_at is not None:
        raise AppError(ErrorCode.VALIDATION, "工作区已注销，不可操作（可在 legacy 目录中复活，随 F3）")
    return row


def _workspace_item(row: Workspace) -> dict[str, Any]:
    directory = workspace_dir_for(row.id)
    summary = folder_summary(directory)
    return {
        "id": row.id,
        "name": row.name,
        "owner_id": row.owner_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted": row.deleted_at is not None,
        "folder": summary,
    }


@router.get("")
def list_workspaces(
    include_deleted: bool = Query(default=False, description="是否包含已注销工作区"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前用户的工作区（默认活跃行；行态随 deleted 字段暴露）。"""
    query = db.query(Workspace).filter(Workspace.owner_id == user.id)
    if not include_deleted:
        query = query.filter(Workspace.deleted_at.is_(None))
    rows = query.order_by(Workspace.updated_at.desc()).all()
    return {"items": [_workspace_item(row) for row in rows], "total": len(rows)}


@router.post("", status_code=201)
def create_workspace(
    body: _NameBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新建工作区：表 + 数据目录（``data/workspaces/<uuid>``）原子创建。"""
    name = body.name.strip()
    if not name:
        raise AppError(ErrorCode.VALIDATION, "工作区名称不能为空")
    # 活跃同名预检（每属主活跃唯一；软删同名行允许存在——复活路径 F3 语义）
    duplicate = (
        db.query(Workspace.id)
        .filter(
            Workspace.owner_id == user.id,
            Workspace.name == name,
            Workspace.deleted_at.is_(None),
        )
        .first()
    )
    if duplicate:
        raise AppError(ErrorCode.VALIDATION, "已存在同名工作区")
    row = Workspace(owner_id=user.id, name=name)
    directory = ""
    try:
        db.add(row)
        db.flush()
        directory = workspace_dir_for(row.id)
        os.makedirs(directory, exist_ok=False)
        write_audit(db, request, user, action="workspace_create", target_type="workspace", target_id=row.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        if directory:
            shutil.rmtree(directory, ignore_errors=True)
        raise AppError(ErrorCode.VALIDATION, "已存在同名工作区") from None
    except OSError as exc:
        db.rollback()
        raise AppError(ErrorCode.INTERNAL, "工作区目录创建失败") from exc
    return _workspace_item(row)


@router.put("/{workspace_id}")
def rename_workspace(
    workspace_id: str,
    body: _NameBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """工作区改名（活跃行；每属主活跃唯一）。"""
    row = _owned_workspace(db, user, workspace_id)
    name = body.name.strip()
    if not name:
        raise AppError(ErrorCode.VALIDATION, "工作区名称不能为空")
    duplicate = (
        db.query(Workspace.id)
        .filter(
            Workspace.owner_id == user.id,
            Workspace.name == name,
            Workspace.deleted_at.is_(None),
            Workspace.id != workspace_id,
        )
        .first()
    )
    if duplicate:
        raise AppError(ErrorCode.VALIDATION, "已存在同名工作区")
    row.name = name
    write_audit(db, request, user, action="workspace_rename", target_type="workspace", target_id=row.id)
    db.commit()
    return _workspace_item(row)


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    request: Request,
    purge: bool = Query(default=False, description="purge=true 真删行与目录（需先注销）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """注销 = 软删（默认）；purge = 显式解绑引用后真删行 + 目录树。"""
    row = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "工作区不存在")
    if row.owner_id != user.id:
        raise AppError(ErrorCode.UNAUTHORIZED, "无权访问该工作区")

    if not purge:
        if row.deleted_at is not None:
            return {"ok": True, "id": workspace_id, "deleted": True}
        row.deleted_at = datetime.now(UTC)
        write_audit(db, request, user, action="workspace_delete", target_type="workspace", target_id=workspace_id)
        db.commit()
        return {"ok": True, "id": workspace_id, "deleted": True}

    # purge：须先经软删（防误触）；行锁已取（workspace → sessions 锁序首行）。
    if row.deleted_at is None:
        raise AppError(ErrorCode.VALIDATION, "purge 前必须先注销工作区（软删）")
    active_bound = (
        db.query(AgentSession.id)
        .filter(
            AgentSession.workspace_id == workspace_id,
            AgentSession.deleted_at.is_(None),
        )
        .first()
    )
    if active_bound:
        raise AppError(
            ErrorCode.CONCURRENCY, "存在活跃绑定会话，禁止 purge（请先结束相关会话）"
        )
    # 显式解绑全部引用（含软删会话行；FK RESTRICT 兜底，绝不用 SET NULL）。
    # 先取解绑会话 id 清单供审计追溯（P2：补 workspace_unbind 语义到 detail）。
    bound_rows = (
        db.query(AgentSession.id)
        .filter(AgentSession.workspace_id == workspace_id)
        .all()
    )
    unbound_ids = [str(row[0]) for row in bound_rows]
    if unbound_ids:
        db.execute(
            update(AgentSession)
            .where(AgentSession.workspace_id == workspace_id)
            .values(workspace_id=None, scope_path=None)
        )
    directory = workspace_dir_for(workspace_id)
    write_audit(
        db,
        request,
        user,
        action="workspace_purge",
        target_type="workspace", target_id=workspace_id,
        detail={
            "unbound_sessions": len(unbound_ids),
            "session_ids": unbound_ids,
            "path": directory,
        },
    )
    db.delete(row)
    db.commit()
    # 事务提交后再清理目录（P5 修复）：行删除是唯一事务事实；目录删除失败
    # 不伪装成功——残留目录进入孤儿清理面兜底，响应明示 residual_dir。
    residual_dir = False
    try:
        shutil.rmtree(directory)
    except OSError:
        residual_dir = True
    return {
        "ok": True,
        "id": workspace_id,
        "purged": True,
        "unbound_sessions": len(unbound_ids),
        "residual_dir": residual_dir,
    }


@router.get("/{workspace_id}/files")
def list_files(
    workspace_id: str,
    path: str = Query(default="", description="相对 scope（空=根）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """一层目录列表 + 当前相对路径（目录进入式浏览，防穿越）。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    entries = list_dir_level(directory, path)
    return {
        "workspace_id": workspace_id,
        "path": path,
        "entries": entries,
        "total": len(entries),
    }


@router.post("/{workspace_id}/files", status_code=201)
def create_folder(
    workspace_id: str,
    body: _FileBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """在工作区相对路径下新建单段文件夹（父目录须已存在）。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    parent = resolve_scope_dir(directory, body.path)
    target = create_child_dir(parent, body.name.strip() or body.name)
    write_audit(
        db,
        request,
        user,
        action="workspace_folder_create",
        target_type="workspace", target_id=workspace_id,
        detail={"path": os.path.join(body.path, body.name).lstrip("./")},
    )
    db.commit()
    rel = os.path.join(body.path, os.path.basename(target)).replace("\\", "/")
    return {"ok": True, "path": rel.lstrip("./")}


@router.get("/{workspace_id}/files/tree")
def get_tree(
    workspace_id: str,
    max_depth: int = Query(default=4, ge=1, le=8),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取工作区目录树结构。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    tree = get_file_tree(directory, max_depth=max_depth)
    return {"workspace_id": workspace_id, "tree": tree}


@router.get("/{workspace_id}/files/content")
def get_file_content(
    workspace_id: str,
    path: str = Query(..., min_length=1, description="文件相对路径"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取单文件文本内容与元信息。超大或二进制文件安全标记。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    result = read_workspace_file(directory, path)
    return {"workspace_id": workspace_id, **result}


@router.put("/{workspace_id}/files/content")
def update_file_content(
    workspace_id: str,
    body: _FileContentBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """写回/保存文件内容。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    res = write_workspace_file(directory, body.path, body.content)
    write_audit(
        db,
        request,
        user,
        action="workspace_file_update",
        target_type="workspace", target_id=workspace_id,
        detail={"path": res["path"], "size": res["size"]},
    )
    db.commit()
    return {"ok": True, "workspace_id": workspace_id, **res}


@router.post("/{workspace_id}/files/file", status_code=201)
def create_file(
    workspace_id: str,
    body: _CreateFileBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """在指定相对路径下新建单文件。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    res = create_workspace_file(directory, body.path, body.name.strip(), body.content)
    write_audit(
        db,
        request,
        user,
        action="workspace_file_create",
        target_type="workspace", target_id=workspace_id,
        detail={"path": res["path"], "name": res["name"]},
    )
    db.commit()
    return {"ok": True, "workspace_id": workspace_id, **res}


@router.patch("/{workspace_id}/files/rename")
def rename_item(
    workspace_id: str,
    body: _RenamePathBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重命名工作区内的文件或目录。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    res = rename_workspace_path(directory, body.path, body.new_name.strip())
    write_audit(
        db,
        request,
        user,
        action="workspace_file_rename",
        target_type="workspace", target_id=workspace_id,
        detail={"old_path": res["old_path"], "new_path": res["new_path"]},
    )
    db.commit()
    return {"ok": True, "workspace_id": workspace_id, **res}


@router.delete("/{workspace_id}/files")
def delete_item(
    workspace_id: str,
    path: str = Query(..., min_length=1, description="相对路径"),
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除工作区内的文件或目录（拒绝删除工作区根）。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    res = delete_workspace_path(directory, path)
    write_audit(
        db,
        request,
        user,
        action="workspace_file_delete",
        target_type="workspace", target_id=workspace_id,
        detail={"path": res["path"]},
    )
    db.commit()
    return {"ok": True, "workspace_id": workspace_id, **res}


VIDEO_AUDIO_MIME_MAP: dict[str, str] = {
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
    "ogv": "video/ogg",
    "ogg": "video/ogg",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "flv": "video/x-flv",
    "wmv": "video/x-ms-wmv",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "m4a": "audio/mp4",
    "weba": "audio/webm",
}


@router.get("/{workspace_id}/files/raw")
def get_raw_file(
    workspace_id: str,
    path: str = Query(..., min_length=1, description="相对路径"),
    download: bool = Query(False, description="是否强制以附件形式下载"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """以原始二进制/文件流方式返回文件（供图片/音视频预览或文件下载）。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)
    abs_path = resolve_scope_file(directory, path, must_exist=True)

    media_type, _ = mimetypes.guess_type(abs_path)
    ext = os.path.splitext(abs_path)[1].lower().lstrip(".")
    if ext in VIDEO_AUDIO_MIME_MAP:
        media_type = VIDEO_AUDIO_MIME_MAP[ext]

    disposition = "attachment" if download else "inline"
    return FileResponse(
        abs_path,
        filename=os.path.basename(abs_path),
        media_type=media_type,
        content_disposition_type=disposition,
    )


@router.post("/{workspace_id}/files/upload", status_code=201)
async def upload_file(
    workspace_id: str,
    file: UploadFile = File(..., description="上传的文件对象"),
    path: str = Form(default="", description="保存的目标父目录相对路径"),
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传文件至指定相对父目录下（支持音视频、图像、数据集等任意文件格式）。"""
    row = _owned_workspace(db, user, workspace_id)
    directory = workspace_dir_for(row.id)

    raw_filename = file.filename or "uploaded_file"
    clean_name = os.path.basename(raw_filename.replace("\\", "/")).strip()
    if not clean_name or clean_name in (".", ".."):
        raise AppError(ErrorCode.VALIDATION, "非法的文件名称")

    clean_parent = (path or "").strip("/").replace("\\", "/")

    content_bytes = await file.read()
    file_size = len(content_bytes)

    from ..config import settings

    quota = int(getattr(settings, "workspace_quota_bytes", 1024 * 1024 * 1024))
    if quota > 0:
        summary = folder_summary(directory) or {"total_bytes": 0}
        target_dir = resolve_scope_dir(directory, clean_parent)
        target_item = os.path.join(target_dir, clean_name)
        existing_file_size = os.path.getsize(target_item) if os.path.isfile(target_item) else 0
        projected_size = summary["total_bytes"] - existing_file_size + file_size
        if projected_size > quota:
            raise AppError(ErrorCode.VALIDATION, f"工作区容量超出配额上限（上限 {quota // (1024 * 1024)}MB）")

    res = save_workspace_file_bytes(directory, clean_parent, clean_name, content_bytes, overwrite=True)
    write_audit(
        db,
        request,
        user,
        action="workspace_file_upload",
        target_type="workspace",
        target_id=workspace_id,
        detail={"path": res["path"], "name": res["name"], "size": res["size"]},
    )
    db.commit()
    return {"ok": True, "workspace_id": workspace_id, **res}
