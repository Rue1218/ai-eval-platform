"""工作区管理接口：会话 → 沙箱文件夹的一一对应视图（管理端）。

- ``GET /api/admin/workspaces``：返回全部会话（含软删除）及其沙箱文件夹摘要
  （文件数 / 占用字节 / 最近活动），并附带磁盘上无对应会话的孤立文件夹；
- ``GET /api/admin/workspaces/{session_id}/files``：展开会话文件夹内的文件清单；
- ``DELETE /api/admin/workspaces/{session_id}``：清理该会话的沙箱文件夹（写审计）。

路径安全：session_id 经 ``session_workspace_dir`` 严格校验（UUID 安全字符集），
禁止路径穿越；文件枚举限制在会话工作区内。
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..harness.execution.workspace import get_workspace_root, session_workspace_dir
from ..models import AuditLog, Session as AgentSession, User

router = APIRouter(prefix="/api/admin/workspaces", tags=["admin-workspaces"])

_MAX_FILES = 500


def _folder_summary(directory: str) -> dict[str, Any] | None:
    """统计工作区文件夹：文件数 / 总字节 / 最近修改时间；目录不存在返回 None。"""
    if not os.path.isdir(directory):
        return None
    file_count = 0
    total_bytes = 0
    last_mtime = 0.0
    for root, _dirs, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            file_count += 1
            total_bytes += st.st_size
            if st.st_mtime > last_mtime:
                last_mtime = st.st_mtime
    return {
        "name": os.path.basename(directory),
        "path": directory,
        "exists": True,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "updated_at": (
            datetime.fromtimestamp(last_mtime, UTC).isoformat() if last_mtime else None
        ),
    }


@router.get("")
def list_workspaces(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出全部会话及其沙箱文件夹摘要，并识别孤立文件夹（磁盘有目录、数据库无会话）。"""
    root = get_workspace_root()
    sessions = db.query(AgentSession).all()
    session_ids = {row.id for row in sessions}

    owners = {
        row.id: row.username
        for row in db.query(User).filter(User.id.in_({s.user_id for s in sessions})).all()
    } if sessions else {}

    items = []
    for session in sessions:
        directory = session_workspace_dir(session.id)
        items.append(
            {
                "session_id": session.id,
                "title": session.title,
                "owner": owners.get(session.user_id),
                "visibility": session.visibility,
                "deleted": session.deleted_at is not None,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "folder": _folder_summary(directory),
            }
        )

    orphans = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if name in session_ids:
                continue
            directory = os.path.join(root, name)
            if not os.path.isdir(directory):
                continue
            summary = _folder_summary(directory)
            if summary:
                orphans.append(summary)

    items.sort(key=lambda item: item["updated_at"] or "", reverse=True)
    return {"root": root, "items": items, "orphans": orphans}


@router.delete("/orphans/{folder_name}")
def delete_orphan(
    folder_name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """清理孤立工作区文件夹（磁盘存在但无对应会话）。

    路径安全：仅接受工作区根目录下的直接子目录名；拒绝路径分隔符、
    ``.`` / ``..`` 与符号链接逃逸，避免误删工作区根以外的内容。
    """
    root = get_workspace_root()
    if (
        not folder_name
        or folder_name in {".", ".."}
        or "/" in folder_name
        or "\\" in folder_name
    ):
        raise AppError(ErrorCode.VALIDATION, "非法文件夹名")
    directory = os.path.join(root, folder_name)
    if os.path.dirname(directory) != root:
        raise AppError(ErrorCode.VALIDATION, "非法文件夹名")
    if os.path.islink(directory) or not os.path.realpath(directory).startswith(
        os.path.realpath(root) + os.sep
    ):
        raise AppError(ErrorCode.VALIDATION, "非法文件夹名")
    if not os.path.isdir(directory):
        return {"ok": False, "reason": "not_found", "path": directory}
    shutil.rmtree(directory)
    db.add(
        AuditLog(
            user_id=user.id,
            action="workspace_cleanup",
            target_type="workspace_orphan",
            target_id=folder_name,
            detail={"path": directory},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    return {"ok": True, "path": directory}


@router.get("/{session_id}/files")
def list_workspace_files(
    session_id: str,
    max_entries: int = Query(default=200, ge=1, le=_MAX_FILES),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出会话工作区内的文件（名称 / 大小 / 修改时间），仅限当前会话目录内。"""
    directory = session_workspace_dir(session_id)  # 严格校验，防路径穿越
    files = []
    if os.path.isdir(directory):
        for root, _dirs, names in os.walk(directory):
            rel_root = os.path.relpath(root, directory)
            for name in sorted(names):
                path = os.path.join(root, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                rel = os.path.join(rel_root, name) if rel_root != "." else name
                files.append(
                    {
                        "name": rel,
                        "size": st.st_size,
                        "updated_at": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
                    }
                )
                if len(files) >= max_entries:
                    break
            if len(files) >= max_entries:
                break
    return {"session_id": session_id, "path": directory, "files": files, "total": len(files)}


@router.delete("/{session_id}")
def delete_workspace(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """清理会话沙箱文件夹（物理删除，软删除的会话工作区同样可清理）。"""
    directory = session_workspace_dir(session_id)  # 严格校验，防路径穿越
    if not os.path.isdir(directory):
        return {"ok": False, "reason": "not_found", "path": directory}
    shutil.rmtree(directory)
    db.add(
        AuditLog(
            user_id=user.id,
            action="workspace_cleanup",
            target_type="session",
            target_id=session_id,
            detail={"path": directory},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    return {"ok": True, "path": directory}
