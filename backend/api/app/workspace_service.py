"""工作区目录服务（用户域单一事实源——设计文档 A V0.4.1）。

目录扫描/统计与路径安全逻辑收敛于此，避免路由复制第二份 ``os.walk`` 语义：

- ``folder_summary``：目录摘要（文件数/总字节/最近活动），用户域使用；
- 路径安全（防穿越/符号链接逃逸，api 侧校验纪律）：
  - ``validate_segment``：单段目录名校验（拒 ``.``/``..``/分隔符）；
  - ``resolve_scope_dir``：在工作区根内解析相对 scope 的绝对目录
    （逐段 realpath 前缀重验，允许尚不存在的新建段）；
- ``list_dir_level``：一层目录列表（目录/文件混合，不递归、不跟随链接）；
- ``create_child_dir``：在已校验父目录下创建单段子目录（父须存在）。

目录拓扑（与 legacy 会话目录**同根共存**）：``data/workspaces/<uuid>`` 为
工作区目录（id 即目录名），``data/workspaces/<session_id>`` 为未绑定会话的
legacy 临时工作区。
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from typing import Any, BinaryIO

from app.errors import AppError, ErrorCode

# 目录名形态校验：uuid（工作区/会话）或任意安全目录段（用户新建文件夹名）
_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")

_MAX_FILES = 500


def workspace_dir_for(workspace_id: str) -> str:
    """校验工作区 id 并返回其数据目录（纯路径计算，不创建）。

    与 ``harness.execution.workspace.session_workspace_dir`` 同根：目录名 =
    行 id（uuid 形态）；防路径穿越由形态校验保证。
    """
    from app.harness.execution.workspace import get_workspace_root

    if not _ID_RE.fullmatch(workspace_id or ""):
        raise AppError(ErrorCode.VALIDATION, "非法工作区标识")
    return os.path.join(get_workspace_root(), workspace_id)


def validate_segment(name: str) -> str:
    """单段目录名校验（新建文件夹/孤儿清理共用）：非空、非 ``.``/``..``、无分隔符。

    段级限制 255 字符（POSIX NAME_MAX）；返回原值。
    """
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or len(name) > 255
        or "/" in name
        or "\\" in name
    ):
        raise AppError(ErrorCode.VALIDATION, "非法目录名：需为单段非空名称")
    return name


def resolve_scope_dir(base: str, rel_scope: str) -> str:
    """在工作区目录 ``base`` 内解析相对 scope，返回绝对目录（防穿越+符号链接）。

    - ``rel_scope`` 为空或 ``"/"`` → ``base``；
    - 每段须过 ``validate_segment``（拒 ``..`` 与分隔符）；
    - 已存在路径段逐段 ``realpath`` 前缀重验（符号链接逃逸拒绝）；
    - 尚不存在的段（将由其后的 mkdir 创建）仅做名字校验——父链已校验，
      不存在即不可能被符号链接指走。
    """
    base_abs = os.path.abspath(base)
    base_real = os.path.realpath(base_abs)
    if not os.path.isdir(base_real):
        raise AppError(ErrorCode.NOT_FOUND, "工作区目录不存在")
    rel = (rel_scope or "").strip("/")
    current = base_abs
    if not rel:
        return current
    for part in rel.split("/"):
        validate_segment(part)
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise AppError(ErrorCode.VALIDATION, "路径含符号链接，拒绝访问")
        if os.path.exists(current):
            real = os.path.realpath(current)
            if real != base_real and not real.startswith(base_real + os.sep):
                raise AppError(ErrorCode.VALIDATION, "路径越出工作区，拒绝访问")
    return os.path.abspath(current)


def folder_summary(directory: str) -> dict[str, Any] | None:
    """统计目录：文件数 / 总字节 / 最近修改时间；目录不存在返回 None。"""
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


def list_dir_level(directory: str, rel_scope: str = "") -> list[dict[str, Any]]:
    """一层目录列表（目录/文件混合，≤``_MAX_FILES``），不递归、不跟随链接。

    相对 scope 的解析与防穿越见 ``resolve_scope_dir``。条目含
    ``name/kind(dir|file|link)/size/updated_at``；链接以 ``kind=link`` 暴露
    但不跟随（浏览仅为元数据展示，杜绝符号链接内容泄露面）。
    """
    target = resolve_scope_dir(directory, rel_scope)
    entries: list[dict[str, Any]] = []
    try:
        with os.scandir(target) as iterator:
            for entry in iterator:
                kind: str
                try:
                    if entry.is_dir(follow_symlinks=False):
                        kind = "dir"
                    elif entry.is_file(follow_symlinks=False):
                        kind = "file"
                    else:
                        kind = "link"
                    st = entry.stat(follow_symlinks=False)
                    size = st.st_size if kind == "file" else 0
                    mtime = st.st_mtime if kind in {"file", "dir"} else 0
                except OSError:
                    continue
                entries.append(
                    {
                        "name": entry.name,
                        "kind": kind,
                        "size": size,
                        "updated_at": (
                            datetime.fromtimestamp(mtime, UTC).isoformat() if mtime else None
                        ),
                    }
                )
                if len(entries) >= _MAX_FILES:
                    break
    except FileNotFoundError:
        raise AppError(ErrorCode.NOT_FOUND, "目录不存在") from None
    except OSError as exc:
        raise AppError(ErrorCode.VALIDATION, "目录读取失败") from exc
    entries.sort(key=lambda item: (item["kind"] != "dir", item["name"].lower()))
    return entries


def create_child_dir(parent: str, name: str) -> str:
    """在已存在父目录下创建单段子目录（幂等：已存在同名目录直接返回）。

    ``name`` 经 ``validate_segment``；父目录须已存在（平台创建的工作区树内）。
    """
    validate_segment(name)
    target = os.path.join(parent, name)
    if os.path.islink(target):
        raise AppError(ErrorCode.VALIDATION, "同名路径为符号链接，拒绝创建")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "目录创建失败") from exc
    if not os.path.isdir(target) or os.path.islink(target):
        raise AppError(ErrorCode.INTERNAL, "目录创建失败")
    return target


def ensure_workspace_scope(workspace_id: str, scope_path: str | None) -> str:
    """绑定目录准备（创建会话时调用，F3/G5）：校验 id/scope 并确保目标目录存在。

    工作区目录须已存在（平台创建）；scope 段可尚不存在（按需 mkdir，仅工作区
    树内）。返回绝对目录供 bind 与 runner ``policy.workspace_root``。
    """
    base = workspace_dir_for(workspace_id)
    target = resolve_scope_dir(base, scope_path or "")
    if os.path.islink(target):
        raise AppError(ErrorCode.VALIDATION, "绑定路径为符号链接")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "目录创建失败") from exc
    if not os.path.isdir(target) or os.path.islink(target):
        raise AppError(ErrorCode.INTERNAL, "目录创建失败")
    return target


def resolve_session_sandbox_db(
    db_session,
    session_id: str,
    workspace_id: str | None,
    scope_path: str | None,
) -> str:
    """带行态校验的会话沙箱唯一解析（ws/附件装配共用，BLK-2 修复）。

    ``resolve_session_sandbox`` 的 DB 版：绑定工作区行必须存在且**未注销**
    （``deleted_at IS NULL``，落实 models.py 注释承诺）——行缺失/已注销 →
    ``AppError(VALIDATION)`` fail-closed（调用方降级空串，绝不回落 legacy）。
    """
    if not workspace_id:
        from app.harness.execution.workspace import ensure_session_workspace

        return ensure_session_workspace(session_id)
    from app.models import Workspace

    ws_row = (
        db_session.query(Workspace).filter(Workspace.id == workspace_id).first()
    )
    if ws_row is None or ws_row.deleted_at is not None:
        raise AppError(ErrorCode.VALIDATION, "绑定工作区已注销或不存在")
    return resolve_session_sandbox(session_id, workspace_id, scope_path)


def resolve_session_sandbox(
    session_id: str,
    workspace_id: str | None,
    scope_path: str | None,
) -> str:
    """会话沙箱唯一解析入口（F3/G5，设计 §5）：绑定 → 工作区 scope；未绑定 → legacy。

    - 未绑定（``workspace_id`` 空）→ ``ensure_session_workspace(session_id)``
      （legacy 自动目录，与 F3 前逐字节一致）；
    - 绑定 → 工作区目录存在 + scope 前缀防穿越解析（``resolve_scope_dir``），
      返回绝对目录；目录不可得（行存在但目录被删等不一致窗口）→
      ``AppError(VALIDATION)`` **fail-closed**——调用方降级空串（工具
      VALIDATION「未配置沙箱目录」），绝不回落 legacy 裸目录。
    """
    if not workspace_id:
        from app.harness.execution.workspace import ensure_session_workspace

        return ensure_session_workspace(session_id)
    base = workspace_dir_for(workspace_id)
    try:
        target = resolve_scope_dir(base, scope_path or "")
    except AppError as exc:
        # 工作区目录缺失 / scope 越界：绑定失效统一 VALIDATION（fail-closed）
        if exc.code == ErrorCode.NOT_FOUND:
            raise AppError(ErrorCode.VALIDATION, "绑定工作区目录不可用") from None
        raise
    if not os.path.isdir(target) or os.path.islink(target):
        raise AppError(ErrorCode.VALIDATION, "绑定工作区目录不可用")
    return target


def resolve_scope_item(base: str, rel_path: str, *, must_exist: bool = True) -> str:
    """在工作区 base 内解析相对条目（文件或目录），严格防穿越 + 符号链接逃逸。"""
    base_abs = os.path.abspath(base)
    base_real = os.path.realpath(base_abs)
    if not os.path.isdir(base_real):
        raise AppError(ErrorCode.NOT_FOUND, "工作区目录不存在")
    rel = (rel_path or "").strip("/").replace("\\", "/")
    if not rel:
        raise AppError(ErrorCode.VALIDATION, "相对路径不能为空")
    current = base_abs
    parts = [p for p in rel.split("/") if p]
    for part in parts:
        validate_segment(part)
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise AppError(ErrorCode.VALIDATION, "路径含符号链接，拒绝访问")
        if os.path.exists(current):
            real = os.path.realpath(current)
            if real != base_real and not real.startswith(base_real + os.sep):
                raise AppError(ErrorCode.VALIDATION, "路径越出工作区，拒绝访问")
    current_abs = os.path.abspath(current)
    if must_exist and not os.path.exists(current_abs):
        raise AppError(ErrorCode.NOT_FOUND, "目标不存在")
    return current_abs


def resolve_scope_file(base: str, rel_path: str, *, must_exist: bool = True) -> str:
    """在工作区 base 内解析相对单文件路径，严格防穿越并确保为文件而非目录。"""
    target = resolve_scope_item(base, rel_path, must_exist=must_exist)
    if must_exist and os.path.isdir(target):
        raise AppError(ErrorCode.VALIDATION, "目标为目录而非文件")
    return target


def read_workspace_file(directory: str, rel_path: str, max_bytes: int = 5 * 1024 * 1024) -> dict[str, Any]:
    """安全读取工作区单文件内容与元数据。超大文件标明 is_large，二进制标明 is_binary。"""
    abs_path = resolve_scope_file(directory, rel_path, must_exist=True)
    try:
        st = os.stat(abs_path)
    except OSError as exc:
        raise AppError(ErrorCode.NOT_FOUND, "文件读取失败") from exc
    size = st.st_size
    mtime = (
        datetime.fromtimestamp(st.st_mtime, UTC).isoformat() if st.st_mtime else None
    )
    is_large = size > max_bytes
    if is_large:
        return {
            "path": rel_path.strip("/").replace("\\", "/"),
            "name": os.path.basename(abs_path),
            "size": size,
            "updated_at": mtime,
            "is_binary": False,
            "is_large": True,
            "content": "",
        }
    try:
        with open(abs_path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "无法读取文件数据") from exc

    is_binary = b"\x00" in raw
    if not is_binary:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            is_binary = True
            content = ""
    else:
        content = ""

    return {
        "path": rel_path.strip("/").replace("\\", "/"),
        "name": os.path.basename(abs_path),
        "size": size,
        "updated_at": mtime,
        "is_binary": is_binary,
        "is_large": False,
        "content": content,
    }


def write_workspace_file(directory: str, rel_path: str, content: str) -> dict[str, Any]:
    """安全写回工作区文本文件内容。"""
    abs_path = resolve_scope_file(directory, rel_path, must_exist=True)
    if os.path.islink(abs_path):
        raise AppError(ErrorCode.VALIDATION, "目标为符号链接，拒绝写入")
    try:
        with open(abs_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        st = os.stat(abs_path)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "写入文件失败") from exc
    return {
        "path": rel_path.strip("/").replace("\\", "/"),
        "name": os.path.basename(abs_path),
        "size": st.st_size,
        "updated_at": (
            datetime.fromtimestamp(st.st_mtime, UTC).isoformat() if st.st_mtime else None
        ),
    }


def create_workspace_file(directory: str, parent_path: str, name: str, content: str = "") -> dict[str, Any]:
    """在指定相对父目录下创建新文件。"""
    validate_segment(name)
    parent_dir = resolve_scope_dir(directory, parent_path)
    target = os.path.join(parent_dir, name)
    if os.path.exists(target) or os.path.islink(target):
        raise AppError(ErrorCode.VALIDATION, "同名文件或目录已存在")
    try:
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        st = os.stat(target)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "创建文件失败") from exc
    rel = os.path.join(parent_path, name).replace("\\", "/").strip("/")
    return {
        "path": rel,
        "name": name,
        "size": st.st_size,
        "updated_at": (
            datetime.fromtimestamp(st.st_mtime, UTC).isoformat() if st.st_mtime else None
        ),
    }


def save_workspace_file_stream(
    directory: str,
    parent_path: str,
    name: str,
    source: BinaryIO,
    *,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """分块写入同目录临时文件，校验配额后原子替换，失败时保留原文件。"""
    validate_segment(name)
    parent_dir = resolve_scope_dir(directory, parent_path)
    target = os.path.join(parent_dir, name)
    if os.path.islink(target):
        raise AppError(ErrorCode.VALIDATION, "目标为符号链接，拒绝写入")
    if os.path.isdir(target):
        raise AppError(ErrorCode.VALIDATION, "目标为目录而非文件")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=parent_dir, prefix=".upload-", delete=False) as f:
            temporary_path = f.name
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise AppError(ErrorCode.VALIDATION, "工作区容量超出配额上限")
                f.write(chunk)
        os.replace(temporary_path, target)
        st = os.stat(target)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "保存文件失败") from exc
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    rel = os.path.join(parent_path, name).replace("\\", "/").strip("/")
    return {
        "path": rel,
        "name": name,
        "size": st.st_size,
        "updated_at": (
            datetime.fromtimestamp(st.st_mtime, UTC).isoformat() if st.st_mtime else None
        ),
    }


def rename_workspace_path(directory: str, rel_path: str, new_name: str) -> dict[str, Any]:
    """在同级目录下重命名文件或目录。"""
    validate_segment(new_name)
    rel = (rel_path or "").strip("/").replace("\\", "/")
    if not rel:
        raise AppError(ErrorCode.VALIDATION, "无法重命名工作区根目录")
    abs_src = resolve_scope_item(directory, rel, must_exist=True)
    parent_dir = os.path.dirname(abs_src)
    abs_dst = os.path.join(parent_dir, new_name)
    if os.path.exists(abs_dst) or os.path.islink(abs_dst):
        raise AppError(ErrorCode.VALIDATION, "目标名称已存在")
    try:
        os.rename(abs_src, abs_dst)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "重命名失败") from exc
    parent_rel = os.path.dirname(rel).replace("\\", "/")
    new_rel = os.path.join(parent_rel, new_name).replace("\\", "/").strip("/")
    return {
        "old_path": rel,
        "new_path": new_rel,
        "name": new_name,
    }


def delete_workspace_path(directory: str, rel_path: str) -> dict[str, Any]:
    """安全删除工作区内的指定文件或目录（拒绝删除工作区根）。"""
    rel = (rel_path or "").strip("/").replace("\\", "/")
    if not rel:
        raise AppError(ErrorCode.VALIDATION, "无法删除工作区根目录")
    abs_target = resolve_scope_item(directory, rel, must_exist=True)
    base_real = os.path.realpath(os.path.abspath(directory))
    target_real = os.path.realpath(abs_target)
    if target_real == base_real:
        raise AppError(ErrorCode.VALIDATION, "无法删除工作区根目录")
    try:
        if os.path.isdir(abs_target) and not os.path.islink(abs_target):
            shutil.rmtree(abs_target)
        else:
            os.remove(abs_target)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "删除失败") from exc
    return {
        "path": rel,
        "deleted": True,
    }


def get_file_tree(directory: str, max_depth: int = 4, max_entries: int = 1000) -> list[dict[str, Any]]:
    """递归获取工作区目录树结构（限定深度与条目数，防 OOM）。"""
    base_abs = os.path.abspath(directory)
    if not os.path.isdir(base_abs):
        return []

    count = 0

    def _scan(current_path: str, rel_prefix: str, current_depth: int) -> list[dict[str, Any]]:
        nonlocal count
        if current_depth > max_depth or count >= max_entries:
            return []
        res = []
        try:
            with os.scandir(current_path) as it:
                items = list(it)
        except OSError:
            return []
        items.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        for entry in items:
            if count >= max_entries:
                break
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
                kind = "dir" if is_dir else ("file" if is_file else "link")
                st = entry.stat(follow_symlinks=False)
                size = st.st_size if kind == "file" else 0
                mtime = st.st_mtime if kind in {"file", "dir"} else 0
            except OSError:
                continue
            count += 1
            rel = os.path.join(rel_prefix, entry.name).replace("\\", "/").strip("/")
            node: dict[str, Any] = {
                "name": entry.name,
                "path": rel,
                "kind": kind,
                "size": size,
                "updated_at": (
                    datetime.fromtimestamp(mtime, UTC).isoformat() if mtime else None
                ),
            }
            if is_dir:
                node["children"] = _scan(entry.path, rel, current_depth + 1)
            res.append(node)
        return res

    return _scan(base_abs, "", 1)
