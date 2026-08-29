"""工作区管理接口：会话 → 沙箱文件夹的一一对应视图（管理端）。

- ``GET /api/admin/workspaces``：分页返回会话（含软删除）及其沙箱文件夹摘要
  （文件数 / 占用字节 / 最近活动），支持关键词 / 文件夹 / 删除状态过滤；
  文件夹扫描只对当前页会话执行，并附带整体聚合 ``stats`` 与孤立文件夹清单；
- ``GET /api/admin/workspaces/stats``：全部工作区磁盘总字节（遍历代价高，供前端后台加载 KPI）；
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
from ..models import AuditLog, User
from ..models import Session as AgentSession

router = APIRouter(prefix="/api/admin/workspaces", tags=["admin-workspaces"])

_MAX_FILES = 500


def _match_session(
    entry: tuple[str | None, str | None, str, bool, bool],
    keyword: str,
    folder: str,
    deleted: str,
) -> bool:
    """单条会话的过滤判定（纯函数，便于单测）。

    ``entry`` 为 ``(title, owner, session_id, has_folder, is_deleted)``；
    ``keyword`` 匹配标题 / 归属 / 会话 ID；``folder`` 取 all/has/none；
    ``deleted`` 取 all/active/deleted。
    """
    title, owner, session_id, has_folder, is_deleted = entry
    if keyword and keyword not in f"{title or ''} {owner or ''} {session_id}".lower():
        return False
    if folder == "has" and not has_folder:
        return False
    if folder == "none" and has_folder:
        return False
    if deleted == "active" and is_deleted:
        return False
    if deleted == "deleted" and not is_deleted:
        return False
    return True


def _paginate_entries(
    entries: list,
    offset: int,
    limit: int,
) -> tuple[list, int]:
    """按会话最近更新时间倒序排序并切片，返回 (当前页, 过滤后总数)。"""
    ordered = sorted(
        entries,
        key=lambda entry: entry[0].updated_at.timestamp() if entry[0].updated_at else 0.0,
        reverse=True,
    )
    return ordered[offset : offset + limit], len(ordered)


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
    offset: int = Query(default=0, ge=0, description="分页偏移，默认 0"),
    limit: int = Query(default=50, ge=1, le=200, description="每页条数，默认 50、最大 200"),
    keyword: str = Query(default="", description="按会话标题 / 归属 / 会话 ID 模糊搜索"),
    folder: str = Query(
        default="all", pattern="^(all|has|none)$", description="工作区文件夹过滤：all/has/none"
    ),
    deleted: str = Query(
        default="all", pattern="^(all|active|deleted)$", description="删除状态过滤：all/active/deleted"
    ),
):
    """分页列出会话及其沙箱文件夹摘要，并识别孤立文件夹（磁盘有目录、数据库无会话）。

    过滤与分页先在会话行上完成（配合一次 ``isdir`` 判断），仅对当前页会话执行
    文件夹扫描统计，避免会话过多时全量 ``os.walk`` 拖慢首屏；``stats`` 为整体
    聚合（不做过滤），供 KPI 卡片使用；磁盘总字节走 ``GET /stats`` 由前端后台加载。
    """
    root = get_workspace_root()
    rows = (
        db.query(AgentSession, User.username)
        .outerjoin(User, AgentSession.user_id == User.id)
        .all()
    )
    kw = keyword.strip().lower()

    # 单次遍历构建 (会话, 归属, 是否有工作区) 三元组，并统计整体聚合
    entries: list[tuple[AgentSession, str | None, bool]] = []
    with_folder = 0
    for session, username in rows:
        has_folder = os.path.isdir(session_workspace_dir(session.id))
        if has_folder:
            with_folder += 1
        entries.append((session, username, has_folder))

    filtered = [
        (session, username)
        for session, username, has in entries
        if _match_session(
            (session.title, username, session.id, has, session.deleted_at is not None),
            kw,
            folder,
            deleted,
        )
    ]
    page_entries, total = _paginate_entries(filtered, offset, limit)

    items = []
    for session, username in page_entries:
        # 仅当前页会话做文件夹扫描，控制单次请求的磁盘遍历规模
        directory = session_workspace_dir(session.id)
        items.append(
            {
                "session_id": session.id,
                "title": session.title,
                "owner": username,
                "visibility": session.visibility,
                "deleted": session.deleted_at is not None,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "folder": _folder_summary(directory),
            }
        )

    orphans = []
    if os.path.isdir(root):
        # 孤立判定必须基于全部会话（含被过滤掉的），避免误把过滤会话当孤立目录
        session_ids = {session.id for session, _username, _has in entries}
        for name in sorted(os.listdir(root)):
            if name in session_ids:
                continue
            directory = os.path.join(root, name)
            if not os.path.isdir(directory):
                continue
            summary = _folder_summary(directory)
            if summary:
                orphans.append(summary)

    return {
        "root": root,
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "stats": {
            "total_sessions": len(entries),
            "with_folder": with_folder,
            "orphan_count": len(orphans),
        },
        "orphans": orphans,
    }


@router.get("/stats")
def workspace_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """统计全部会话工作区的磁盘总字节（KPI「工作区总大小」）。

    需要遍历所有会话工作区内的文件，代价较高；由前端在列表渲染完成后
    异步调用，不阻塞工作区表格的首屏。
    """
    total_bytes = 0
    for (session_id,) in db.query(AgentSession.id).all():
        summary = _folder_summary(session_workspace_dir(session_id))
        if summary:
            total_bytes += summary["total_bytes"]
    return {"total_bytes": total_bytes}


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
