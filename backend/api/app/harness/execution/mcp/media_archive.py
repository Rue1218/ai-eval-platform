"""媒体结果的平台侧归档：把上游临时图片/视频落到会话工作区。

沙箱没有公网出口，模型与 bash 都无法取回上游媒体（临时链接约 24 小时有效）；
api 是唯一同时具备公网出口与工作区写权限的组件，因此在工具结果返回前尽力把
媒体下载进 ``<工作区>/media/``，并在 data 追加 ``workspace_images`` /
``workspace_videos`` 相对路径，供 read/read_image 与后续处理使用。下载严格
限制为 HTTPS 公网地址、已知媒体类型与按类别的字节上限；失败只记脱敏类别日志，
绝不改写原工具结果。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolResult

from ..dispatch_common import _reject_internal_target

logger = logging.getLogger("ai-eval.api.media_archive")

# 归档目录与下载约束：归档产物与附件（attachments/）分开，避免与用户上传混淆。
MEDIA_DIRNAME = "media"


@dataclass(frozen=True, slots=True)
class _MediaKind:
    """一类待归档媒体：文件名前缀、类型白名单、大小/时长上限与结果字段名。"""

    label: str
    field: str
    content_types: Mapping[str, str]
    max_bytes: int
    timeout_s: float


_IMAGE = _MediaKind(
    label="image",
    field="workspace_images",
    content_types={
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
    },
    max_bytes=20 * 1024 * 1024,
    timeout_s=30.0,
)
_VIDEO = _MediaKind(
    label="video",
    field="workspace_videos",
    content_types={"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"},
    # 500MB 级视频必须流式落盘（api 容器内存上限 512MB），下载超时相应放宽。
    max_bytes=500 * 1024 * 1024,
    timeout_s=600.0,
)

# 流式下载分块：内存占用与文件大小解耦，只保留单个分块。
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _validate_media_url(url: str) -> str:
    """仅接受无凭据的 HTTPS 公网地址，并阻断内网/回环解析结果（SSRF）。"""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise AppError(ErrorCode.VALIDATION, "媒体地址必须为无凭据的 HTTPS 地址")
    _reject_internal_target(parsed.hostname)
    return parsed.geturl()


class _MediaRedirectHandler(HTTPRedirectHandler):
    """每个重定向都重新执行归档网络校验，阻断跳转绕过。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001,D102
        _validate_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_media(url: str, kind: _MediaKind, target: str) -> str:
    """受控流式下载到 ``target``，返回 content-type；类型或大小超限即拒绝。

    分块写盘，500MB 级视频不会整块驻留内存；超限/失败时由调用方清理半成品。
    """
    request = Request(
        _validate_media_url(url),
        headers={"User-Agent": "ai-eval-platform/1.0", "Accept": "*/*"},
    )
    written = 0
    try:
        opener = build_opener(_MediaRedirectHandler())
        with opener.open(request, timeout=kind.timeout_s) as response:
            content_type = response.headers.get_content_type()
            if content_type not in kind.content_types:
                raise AppError(ErrorCode.UPSTREAM, "上游媒体类型不受支持")
            with open(target, "wb") as handle:
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > kind.max_bytes:
                        raise AppError(ErrorCode.UPSTREAM, "上游媒体超过大小上限")
                    handle.write(chunk)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "媒体下载失败") from exc
    if written == 0:
        raise AppError(ErrorCode.UPSTREAM, "上游媒体为空")
    return content_type


def _media_links(data: Mapping[str, object]) -> tuple[_MediaKind, list[str]] | None:
    """按结果字段判定待归档媒体：生图取 image_urls，视频查状态取 video_url。"""
    images = [item for item in (data.get("image_urls") or []) if isinstance(item, str) and item]
    if images:
        return _IMAGE, images
    video = data.get("video_url")
    if isinstance(video, str) and video:
        return _VIDEO, [video]
    return None


def _url_digest(url: str) -> str:
    """URL 内容摘要：同一地址重复归档落到同一文件名（幂等）。"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def _existing_relative(sandbox_dir: str, kind: _MediaKind, url: str) -> str | None:
    """已归档过同一 URL 时直接复用（避免重复下载），否则返回 None。"""
    directory = os.path.join(sandbox_dir, MEDIA_DIRNAME)
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    prefix = f"{kind.label}-{_url_digest(url)}."
    for name in sorted(names):
        if name.startswith(prefix) and os.path.isfile(os.path.join(directory, name)):
            return f"{MEDIA_DIRNAME}/{name}"
    return None


def _archive_one(
    url: str,
    sandbox_dir: str,
    kind: _MediaKind,
    download: Callable[[str, _MediaKind, str], str],
) -> str:
    """下载单个媒体并经同目录临时文件原子发布；返回工作区相对路径。"""
    existing = _existing_relative(sandbox_dir, kind, url)
    if existing is not None:
        return existing
    directory = os.path.join(sandbox_dir, MEDIA_DIRNAME)
    os.makedirs(directory, exist_ok=True)
    digest = _url_digest(url)
    staging = os.path.join(directory, f".{kind.label}-{digest}-{uuid4().hex}.staging")
    try:
        content_type = download(url, kind, staging)
        filename = f"{kind.label}-{digest}{kind.content_types[content_type]}"
        os.replace(staging, os.path.join(directory, filename))
        return f"{MEDIA_DIRNAME}/{filename}"
    finally:
        with suppress(FileNotFoundError):
            os.unlink(staging)


def _archive_urls_sync(
    urls: list[str],
    sandbox_dir: str,
    kind: _MediaKind,
    download: Callable[[str, _MediaKind, str], str],
) -> list[str]:
    """逐个下载并写入工作区；单个失败只记异常类别，不影响其余媒体。"""
    saved: list[str] = []
    for url in urls:
        try:
            saved.append(_archive_one(url, sandbox_dir, kind, download))
        except Exception as exc:  # noqa: BLE001 —— 归档尽力而为，绝不失败工具调用
            logger.warning("media archive item failed kind=%s", type(exc).__name__)
    return saved


async def archive_media_results(
    result: ToolResult,
    sandbox_dir: str | None,
    *,
    download: Callable[[str, _MediaKind, str], str] | None = None,
) -> ToolResult:
    """把成功的媒体结果归档进会话工作区；任何失败都保持原结果不变。

    ``workspace_images`` / ``workspace_videos`` 为工作区相对路径（与
    read/read_image/bash 同一根），原 ``image_urls`` / ``video_url`` 保留，
    浏览器预览与本地文件互不影响。
    """
    if not result.ok or not sandbox_dir:
        return result
    data = result.data if isinstance(result.data, Mapping) else {}
    links = _media_links(data)
    if links is None:
        return result
    kind, urls = links
    saved = await asyncio.to_thread(_archive_urls_sync, urls, sandbox_dir, kind, download or _download_media)
    if not saved:
        return result
    return replace(result, data={**dict(data), kind.field: saved})
