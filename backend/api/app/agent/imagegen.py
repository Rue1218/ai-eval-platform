"""Qwen Image 图像生成短工具：文本或参考图 + 提示词 → 图片文件。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from ..config import settings
from ..errors import AppError, ErrorCode
from ..models import StoredFile, uuid_str
from .log import agent_trace

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def is_image_file(row: StoredFile | None) -> bool:
    """判断文件元数据是否为可作为参考图的图片。"""
    if row is None:
        return False
    content_type = (row.content_type or "").lower()
    if content_type in IMAGE_MIME_TYPES:
        return True
    return Path(row.filename or "").suffix.lower() in IMAGE_SUFFIXES


def list_image_file_ids(db: Session, attachments: list[str]) -> list[str]:
    """按本轮附件顺序筛出图片 file_id。"""
    ids = [file_id for file_id in attachments if isinstance(file_id, str) and file_id]
    if not ids:
        return []
    rows = db.query(StoredFile).filter(StoredFile.id.in_(ids)).all()
    by_id = {row.id: row for row in rows}
    return [file_id for file_id in ids if is_image_file(by_id.get(file_id))]


def pick_image_file_id(db: Session, attachments: list[str]) -> str:
    """取本轮最后一张图片作为参考图，避免模型编造文件 ID。"""
    image_ids = list_image_file_ids(db, attachments)
    return image_ids[-1] if image_ids else ""


def arguments_for_imagegen(db: Session, *, text: str, attachments: list[str]) -> dict[str, Any]:
    """由本轮原文与附件组装图像工具入参。"""
    return {
        "prompt": (text or "").strip(),
        "file_id": pick_image_file_id(db, attachments),
        "prompt_extend": True,
    }


def _mime_for_filename(filename: str) -> str:
    """根据图片后缀推断 MIME 类型。"""
    suffix = Path(filename).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")


def _sniff_image_mime(data: bytes, fallback: str = "image/png") -> str:
    """根据图片文件头校正 MIME 类型。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback if fallback in IMAGE_MIME_TYPES else "image/png"


def _validate_image(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """校验图片内容和大小，防止异常响应直接落盘。"""
    if not data:
        raise AppError(ErrorCode.UPSTREAM, "上游返回空图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise AppError(ErrorCode.UPSTREAM, "图片超过 20MB 限制")
    return data, _sniff_image_mime(data, mime_type)


def _decode_data_uri(value: str) -> tuple[bytes, str]:
    """解码上游返回的 data URI 图片。"""
    try:
        header, encoded = value.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "image/png"
        if not header.startswith("data:") or ";base64" not in header:
            raise ValueError
        return base64.b64decode(encoded, validate=True), mime_type
    except (ValueError, binascii.Error) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游图片数据无法解析") from exc


def _as_image_reference(item: object) -> tuple[str, str] | None:
    """从响应 content 块提取 URL、data URI 或 Base64 图片。"""
    if not isinstance(item, dict):
        return None
    for key in ("image", "image_url", "url"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("image_url")
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            return normalized, "data_uri" if normalized.startswith("data:") else "url"
    value = item.get("b64_json")
    if isinstance(value, str) and value.strip():
        return value.strip(), "base64"
    return None


def _extract_image_reference(payload: object) -> tuple[str, str]:
    """兼容 Qwen Image 常见响应结构，提取第一张生成图片。"""
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常")
    output = payload.get("output")
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                blocks = content if isinstance(content, list) else [content]
                for block in blocks:
                    reference = _as_image_reference(block)
                    if reference:
                        return reference
        direct = _as_image_reference(output)
        if direct:
            return direct
    data_items = payload.get("data")
    if isinstance(data_items, list):
        for item in data_items:
            reference = _as_image_reference(item)
            if reference:
                return reference
    raise AppError(ErrorCode.UPSTREAM, "上游未返回图片")


def _download_image(url: str, timeout_s: float) -> tuple[bytes, str]:
    """下载上游临时图片 URL，不把 URL 或响应原文写入日志。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AppError(ErrorCode.UPSTREAM, "上游图片地址无效")
    request = Request(url, headers={"User-Agent": "ai-eval-platform-imagegen/1.0"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
            content_type = response.headers.get_content_type() or "image/png"
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"图片下载失败（上游返回 {exc.code}）") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "图片下载超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise AppError(ErrorCode.TIMEOUT, "图片下载超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "图片下载失败") from exc
    return _validate_image(data, content_type)


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    """同步调用 Qwen Image 接口，便于由 Harness 在线程中执行。"""
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode())


def generate_image_bytes(*, prompt: str, ref_bytes: bytes | None = None, ref_mime: str = "image/png", prompt_extend: bool = True) -> tuple[bytes, str]:
    """调用 Qwen Image，支持纯文本或文本+参考图输入。"""
    api_key = (settings.qwen_image_api_key or "").strip()
    api_url = (settings.qwen_image_api_url or "").strip()
    model = (settings.qwen_image_model or "").strip()
    if not api_key or not api_url or not model:
        raise AppError(ErrorCode.VALIDATION, "图像生成未配置 URL、API Key 或模型 ID，请联系管理员")
    timeout_s = float(settings.qwen_image_timeout_seconds or 120.0)
    content: list[dict[str, str]] = []
    if ref_bytes is not None:
        content.append({"image": f"data:{ref_mime};base64,{base64.b64encode(ref_bytes).decode('ascii')}"})
    content.append({"text": prompt})
    body = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"prompt_extend": prompt_extend},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    agent_trace(f"图像生成开始 model={model} has_reference={ref_bytes is not None} timeout={int(timeout_s)}s")
    try:
        payload = _post_json(api_url, body, headers, timeout_s)
        value, kind = _extract_image_reference(payload)
        if kind == "data_uri":
            return _validate_image(*_decode_data_uri(value))
        if kind == "base64":
            data = base64.b64decode(value, validate=True)
            return _validate_image(data, "image/png")
        return _download_image(value, timeout_s)
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "图像生成超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise AppError(ErrorCode.TIMEOUT, "图像生成超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc
    except (binascii.Error, json.JSONDecodeError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游图片数据无法解析") from exc
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"图像生成内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "操作失败") from exc


def _persist_image_bytes(db: Session, *, content: bytes, mime_type: str, user_id: str) -> StoredFile:
    """把生成图片写入本地卷并登记 files 表。"""
    extension = {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(mime_type, ".png")
    file_id = uuid_str()
    storage_dir = Path(settings.data_dir) / "files"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / file_id
    storage_path.write_bytes(content)
    stored = StoredFile(
        id=file_id,
        filename=f"imagegen{extension}",
        content_type=mime_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(storage_path),
        kind=extension.lstrip("."),
        uploaded_by=user_id,
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


def execute_imagegen(db: Session, arguments: dict | None, *, user_id: str) -> dict[str, Any]:
    """读取本轮参考图、调用上游并返回图片文件元数据，不回传二进制。"""
    args = arguments if isinstance(arguments, dict) else {}
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise AppError(ErrorCode.VALIDATION, "请输入图像生成提示词")
    file_id = str(args.get("file_id") or "").strip()
    ref_bytes: bytes | None = None
    ref_mime = "image/png"
    if file_id:
        stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
        if not stored or not is_image_file(stored):
            raise AppError(ErrorCode.VALIDATION, "参考文件须为 png、jpg、jpeg、webp 或 gif 图片")
        path = Path(stored.storage_path)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "参考图片不存在")
        ref_bytes = path.read_bytes()
        ref_bytes, ref_mime = _validate_image(ref_bytes, stored.content_type or _mime_for_filename(stored.filename))
    prompt_extend = args.get("prompt_extend", True)
    if isinstance(prompt_extend, str):
        prompt_extend = prompt_extend.lower() not in {"0", "false", "no", "off"}
    image_bytes, mime_type = generate_image_bytes(
        prompt=prompt,
        ref_bytes=ref_bytes,
        ref_mime=ref_mime,
        prompt_extend=bool(prompt_extend),
    )
    out = _persist_image_bytes(db, content=image_bytes, mime_type=mime_type, user_id=user_id)
    agent_trace(f"图像生成完成 bytes={out.size_bytes} mime={out.content_type}")
    return {
        "file_id": out.id,
        "filename": out.filename,
        "content_type": out.content_type,
        "size": out.size_bytes,
        "content_url": f"/api/files/{out.id}/content",
    }


# 用例生成优先：避免「生成登录模块测试用例」被生图口令误伤
_TESTCASE_BLOCK_RE = re.compile(r"(测试用例|生成用例|用例集|\bPRD\b)")
# 「生成一张人像摄影 / 竖幅照片」也要命中；不要要求 12 字内必须出现「图片」
IMAGEGEN_CLARIFY_RE = re.compile(
    r"("
    r"生图|"
    r"生成.{0,16}(图片|图像|照片|相片|海报|插画|壁纸|头像|人像|写真|摄影|图)|"
    r"生成.{0,8}张|"
    r"画一(张|幅)|"
    r"绘制.{0,8}(图片|图像|海报|插画|人像)|"
    r"(竖幅|横幅).{0,12}(人像|摄影|照片|海报)|"
    r"(人像|户外).{0,8}摄影|"
    r"帮我画|"
    r"改图|图片编辑|参考图|"
    r"(?:图|图片|图像).{0,8}(改成|编辑|转换)|"
    r"(?:generate|create|edit)\s+(?:an?\s+)?image"
    r")",
    re.IGNORECASE,
)


def looks_like_image_generation(text: str) -> bool:
    """判断自然语言是否在要求生成或编辑图片（不含测试用例）。"""
    raw = text or ""
    if _TESTCASE_BLOCK_RE.search(raw):
        return False
    return bool(IMAGEGEN_CLARIFY_RE.search(raw))


def _apply_imagegen_plan(plan: Any, *, notes: str) -> Any:
    """把规划改成只跑生图，清掉评测技能、清单工具和偏好思考卡。"""
    plan.intent = "chat"
    plan.skill_id = None
    plan.tools_needed = ["image.generate"]
    plan.delivery = "text"
    plan.slots = {"filled": {}, "missing": []}
    plan.notes = notes
    if hasattr(plan, "pref_thoughts"):
        plan.pref_thoughts = []
    return plan


def inject_imagegen_plan(
    db: Session,
    plan: Any,
    *,
    text: str,
    attachments: list[str],
) -> Any:
    """自然语言回合按图片意图注入图像工具，参考图由本轮附件自动绑定。"""
    if plan.intent in {"cancel", "rerun", "compact", "report", "testcase"}:
        return plan
    explicit_image_request = looks_like_image_generation(text)
    already_planned = "image.generate" in (plan.tools_needed or [])
    has_reference_image = bool(list_image_file_ids(db, attachments))
    edit_with_reference = has_reference_image and any(
        word in (text or "") for word in ("改成", "变成", "转换", "编辑", "优化", "重绘", "风格")
    )
    if not explicit_image_request and not edit_with_reference and not already_planned:
        return plan
    if not (text or "").strip():
        plan.intent = "chat"
        plan.skill_id = None
        plan.tools_needed = []
        plan.delivery = "clarify"
        plan.notes = "规划：请先输入图像生成提示词"
        if hasattr(plan, "pref_thoughts"):
            plan.pref_thoughts = []
        return plan
    return _apply_imagegen_plan(plan, notes="规划：使用 Qwen Image 生成图片")
