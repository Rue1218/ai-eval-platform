"""Agent 用户附件的权限校验、预览元数据和模型上下文投影。"""

from __future__ import annotations

import base64
import mimetypes
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from ..models import Message, StoredFile

# 附件解析只在 Agent 短回合内执行，必须设置硬上限，避免大文件阻塞 API 进程。
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS_PER_FILE = 12_000
MAX_CONTEXT_CHARS = 32_000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".txt", ".html", ".json", ".yaml", ".yml", ".csv", ".jsonl"}
# 懒加载附件：所有可读文本 staging 进会话工作区，由模型用 read 工具按需读取。
# 统一路径后，CSV/JSON/YAML 不再和 TXT/Markdown 走两套截断策略。
TEXT_LAZY_SUFFIXES = TEXT_SUFFIXES


def _file_id(item: object) -> str:
    """从历史字符串或当前对象引用中读取文件 ID。"""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict) and isinstance(item.get("file_id"), str):
        return item["file_id"].strip()
    return ""


def _attachment_ids(attachments: object) -> list[str]:
    """校验消息附件引用格式，并按原始顺序去重。"""
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise AppError(ErrorCode.VALIDATION, "attachments 格式不正确")
    result: list[str] = []
    for item in attachments:
        file_id = _file_id(item)
        if not file_id:
            raise AppError(ErrorCode.VALIDATION, "attachments 格式不正确")
        if file_id not in result:
            result.append(file_id)
    return result


def load_message_files(
    db: Session,
    attachments: object,
    *,
    owner_id: str | None = None,
) -> list[StoredFile]:
    """读取消息附件对应的文件实体，可按消息作者限制上传者。"""
    file_ids = _attachment_ids(attachments)
    if not file_ids:
        return []
    query = db.query(StoredFile).filter(StoredFile.id.in_(file_ids))
    if owner_id:
        query = query.filter(StoredFile.uploaded_by == owner_id)
    rows = query.all()
    by_id = {row.id: row for row in rows}
    return [by_id[file_id] for file_id in file_ids if file_id in by_id]


def normalize_attachment_refs(
    db: Session,
    attachments: object,
    *,
    owner_id: str,
) -> list[dict[str, Any]]:
    """校验当前用户上传的附件，并保存可供历史回放的安全元数据。"""
    file_ids = _attachment_ids(attachments)
    if not file_ids:
        return []
    rows = load_message_files(db, file_ids, owner_id=owner_id)
    if len(rows) != len(file_ids):
        raise AppError(ErrorCode.VALIDATION, "附件不存在或不属于当前用户")
    by_id = {row.id: row for row in rows}
    return [
        {
            "file_id": file_id,
            "filename": by_id[file_id].filename,
            "size": int(by_id[file_id].size_bytes),
            "content_type": by_id[file_id].content_type,
            "content_url": f"/api/files/{file_id}/content",
        }
        for file_id in file_ids
    ]


def normalize_history_attachments(db: Session, attachments: object) -> list[object]:
    """为历史消息补齐安全元数据；旧文件已被清理时保留原始引用。"""
    file_ids = _attachment_ids(attachments)
    if not file_ids:
        return []
    rows = load_message_files(db, file_ids)
    by_id = {row.id: row for row in rows}
    result: list[object] = []
    for file_id in file_ids:
        stored = by_id.get(file_id)
        if stored is None:
            result.append(file_id)
            continue
        result.append(
            {
                "file_id": file_id,
                "filename": stored.filename,
                "size": int(stored.size_bytes),
                "content_type": stored.content_type,
                "content_url": f"/api/files/{file_id}/content",
            }
        )
    return result


def _workspace_attachment_path(file_id: str, filename: str) -> str:
    """会话工作区内附件文件名（file_id 前缀防重名，原始名便于模型识别）。"""
    return f"{file_id}-{Path(filename).name}"


def stage_attachments(session_id: str, files: list[StoredFile]) -> None:
    """把文本附件复制到会话工作区，供 read 工具读取（幂等）。

    - 目标相对路径 ``attachments/{file_id}-{name}``（沙箱内，防目录穿越边界不变）；
    - 复制到工作区的新 inode，避免 bash 原地写入时篡改 ``/data/files`` 原文件；
    - 临时文件经同目录原子发布，避免并发 staging 覆盖已有的工作区文件；
    - 目标已存在时跳过（幂等），不覆盖模型可能已改写的文件。
    """
    from ..harness.execution.workspace import ensure_session_workspace

    if not files:
        return
    workspace = ensure_session_workspace(session_id)
    attach_dir = os.path.join(workspace, "attachments")
    os.makedirs(attach_dir, exist_ok=True)
    for stored in files:
        if Path(stored.filename).suffix.lower() not in TEXT_LAZY_SUFFIXES:
            continue
        source = Path(stored.storage_path)
        if not source.is_file():
            continue
        target = os.path.join(attach_dir, _workspace_attachment_path(stored.id, stored.filename))
        if os.path.exists(target):
            continue
        temporary = os.path.join(attach_dir, f".{stored.id}-{uuid4().hex}.staging")
        try:
            shutil.copyfile(source, temporary)
            try:
                # 同目录硬链接只用于原子占位；源文件已是副本，最终不会与上传卷共享 inode。
                os.link(temporary, target)
            except FileExistsError:
                continue
            except OSError:
                # 极少数文件系统不支持 hard link 时，使用 O_EXCL 保留同样的不覆盖语义。
                try:
                    with open(temporary, "rb") as source_handle, open(target, "xb") as target_handle:
                        shutil.copyfileobj(source_handle, target_handle)
                except FileExistsError:
                    continue
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _read_limited(path: Path) -> bytes:
    """读取有限字节数，避免把上传文件完整复制到 Agent 进程内存。"""
    with path.open("rb") as handle:
        return handle.read(MAX_TEXT_BYTES + 1)


def _truncate(text: str, limit: int = MAX_TEXT_CHARS_PER_FILE) -> str:
    """清理并截断单个附件正文，给模型保留明确的截断标记。"""
    value = text.replace("\x00", "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n…[附件正文已截断]"


def _extract_docx(path: Path) -> str:
    """从 DOCX 的正文 XML 提取段落文本，不依赖 Office 进程。"""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    lines: list[str] = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        parts = [
            node.text or ""
            for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        ]
        if parts:
            lines.append("".join(parts))
    return "\n".join(lines)


def _extract_xlsx(path: Path) -> str:
    """按工作表读取 XLSX 前 80 行，转换成模型可读的制表文本。"""
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        lines: list[str] = []
        for sheet in workbook.worksheets:
            lines.append(f"[工作表：{sheet.title}]")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= 80:
                    lines.append("…[工作表行数已截断]")
                    break
                values = ["" if value is None else str(value) for value in row[:30]]
                if any(values):
                    lines.append("\t".join(values))
        return "\n".join(lines)
    finally:
        workbook.close()


def _extract_pdf(path: Path) -> str:
    """提取 PDF 页面文字；解析失败时返回受控提示，不暴露内部异常。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages[:40]:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
        if sum(len(item) for item in pages) >= MAX_TEXT_CHARS_PER_FILE:
            break
    return "\n\n".join(pages)


def _extract_document(stored: StoredFile) -> str:
    """按扩展名解析文本、PDF、DOCX 或 XLSX。"""
    path = Path(stored.storage_path)
    if not path.is_file():
        return "（文件内容暂不可读取，请通过前端预览或下载查看。）"
    suffix = Path(stored.filename).suffix.lower()
    try:
        if suffix in TEXT_SUFFIXES:
            return _read_limited(path).decode("utf-8-sig", errors="replace")
        if suffix == ".pdf":
            return _extract_pdf(path)
        if suffix == ".docx":
            return _extract_docx(path)
        if suffix == ".xlsx":
            return _extract_xlsx(path)
    except Exception:
        return "（该附件正文解析失败，请通过前端预览或下载查看。）"
    if suffix in {".doc", ".xls"}:
        return "（旧版 Office 格式暂不支持服务端正文提取，请通过前端打开或下载查看。）"
    if suffix in {".wav", ".mp3"}:
        return "（音频附件已上传；如需转写，请使用音频处理能力。）"
    return "（该附件为二进制文件，模型仅收到文件名和类型信息。）"


def _content_type(stored: StoredFile) -> str:
    """读取可信的内容类型，缺失时按扩展名推断。"""
    return stored.content_type or mimetypes.guess_type(stored.filename)[0] or "application/octet-stream"


def _image_part(stored: StoredFile) -> dict[str, Any] | None:
    """将小型图片转换成内部图片内容块，交由适配器转换为三协议格式。"""
    path = Path(stored.storage_path)
    if not path.is_file() or int(stored.size_bytes) > MAX_IMAGE_BYTES:
        return None
    try:
        content = _read_limited(path)
        if len(content) > MAX_IMAGE_BYTES:
            return None
        encoded = base64.b64encode(content).decode("ascii")
    except OSError:
        return None
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{_content_type(stored)};base64,{encoded}"},
    }


def build_model_content(
    prompt: str,
    files: list[StoredFile],
    *,
    workspace_dir: str | None = None,
) -> str | list[dict[str, Any]]:
    """把用户正文、可解析文档和图片合成一次模型请求内容。

    txt/md 附件在 ``workspace_dir`` 可用时改为「路径清单」形式：模型用 read
    工具按需读取（懒加载省 token）；未提供工作区（历史/离线上下文）时回退
    内联注入。图片仍以内部图片块附加；pdf/docx/xlsx 等保持内联抽取（后续
    版本再迁移到 read 工具路径）。
    """
    text = prompt.strip() or "请阅读并处理以下附件。"
    if not files:
        return text

    sections: list[str] = []
    image_parts: list[dict[str, Any]] = []
    for stored in files:
        label = f"{stored.filename} · {_content_type(stored)} · {int(stored.size_bytes)} bytes"
        suffix = Path(stored.filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} or _content_type(stored).startswith("image/"):
            image_part = _image_part(stored)
            if image_part:
                image_parts.append(image_part)
                sections.append(f"- {label}（图片已附加，请结合图片内容回答）")
            else:
                sections.append(f"- {label}（图片过大或读取失败，本轮未传给模型）")
            continue
        if suffix in TEXT_LAZY_SUFFIXES and workspace_dir:
            rel = f"attachments/{_workspace_attachment_path(stored.id, stored.filename)}"
            sections.append(
                f"### {label}\n"
                f"（文本附件已放入会话工作区，相对路径 {rel}。"
                f"请用 read 工具读取该文件内容后再回答；长内容请用 offset/limit 分段读取。）"
            )
            continue
        body = _truncate(_extract_document(stored))
        sections.append(f"### {label}\n{body or '（未提取到可读正文。）'}")

    attachment_text = "【用户附件】\n" + "\n\n".join(sections)
    if len(attachment_text) > MAX_CONTEXT_CHARS:
        attachment_text = attachment_text[:MAX_CONTEXT_CHARS] + "\n…[附件上下文已截断]"
    combined = f"{text}\n\n{attachment_text}"
    if not image_parts:
        return combined
    return [{"type": "text", "text": combined}, *image_parts]


def model_content_for_message(db: Session, row: Message) -> str | list[dict[str, Any]]:
    """读取一条 user 消息的附件，并生成只供模型使用的上下文内容。

    同时把 txt/md 附件 staging 进会话工作区（幂等），使 read 工具可读。
    """
    files = load_message_files(db, row.attachments or [], owner_id=row.author_id)
    workspace_dir: str | None = None
    if files:
        from ..harness.execution.workspace import ensure_session_workspace

        workspace_dir = ensure_session_workspace(row.session_id)
        stage_attachments(row.session_id, files)
    return build_model_content(row.content, files, workspace_dir=workspace_dir)
