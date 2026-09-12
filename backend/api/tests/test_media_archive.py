"""媒体归档测试：不触网、不调用真实模型，只验证工作区落盘契约。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from email.message import Message

import pytest

import app.harness.execution.mcp.media_archive as media_archive
from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolResult
from app.harness.execution import MCPClientManager, ToolDef, ToolRegistry
from app.harness.execution.mcp import ToolExecutionContext
from app.harness.execution.mcp.streamable_provider import StreamableHttpProvider

_IMAGE_URL = "https://result.example/image.png"
_VIDEO_URL = "https://result.example/video.mp4"


def _image_result(*urls: str) -> ToolResult:
    return ToolResult(
        name="image.generate",
        ok=True,
        data={"status": "succeeded", "model": "qwen-image-3.0-pro", "image_urls": list(urls)},
        call_id="c1",
    )


def _video_result(url: str) -> ToolResult:
    return ToolResult(
        name="video.status",
        ok=True,
        data={"status": "SUCCEEDED", "upstream_task_id": "task-1", "video_url": url},
        call_id="c1",
    )


def _mp4_fetch(_url: str, _kind: media_archive._MediaKind) -> tuple[bytes, str]:
    return b"mp4-bytes", "video/mp4"


@pytest.mark.asyncio
async def test_archive_writes_workspace_files_and_keeps_urls(tmp_path) -> None:
    """图片归档落入 <工作区>/media/，data 追加相对路径且保留原 URL。"""
    calls: list[str] = []

    def fetch(url: str, _kind: media_archive._MediaKind) -> tuple[bytes, str]:
        calls.append(url)
        return b"png-bytes", "image/png"

    result = await media_archive.archive_media_results(_image_result(_IMAGE_URL), str(tmp_path), fetch=fetch)

    assert calls == [_IMAGE_URL]
    relative = result.data["workspace_images"][0]
    assert relative.startswith("media/image-") and relative.endswith(".png")
    assert (tmp_path / relative).read_bytes() == b"png-bytes"
    assert result.data["image_urls"] == [_IMAGE_URL]
    # 归档不写任何暂存残留文件
    assert not list((tmp_path / "media").glob("*.staging"))


@pytest.mark.asyncio
async def test_archive_writes_video_into_workspace(tmp_path) -> None:
    """video.status 成功结果中的临时视频地址同样归档并追加 workspace_videos。"""
    result = await media_archive.archive_media_results(_video_result(_VIDEO_URL), str(tmp_path), fetch=_mp4_fetch)

    relative = result.data["workspace_videos"][0]
    assert relative.startswith("media/video-") and relative.endswith(".mp4")
    assert (tmp_path / relative).read_bytes() == b"mp4-bytes"
    assert result.data["video_url"] == _VIDEO_URL
    assert "workspace_images" not in result.data


@pytest.mark.asyncio
async def test_archive_is_idempotent_for_same_url(tmp_path) -> None:
    """同一 URL 重复归档直接复用既有文件，不重复下载。"""
    calls: list[str] = []

    def fetch(url: str, _kind: media_archive._MediaKind) -> tuple[bytes, str]:
        calls.append(url)
        return b"png-bytes", "image/png"

    first = await media_archive.archive_media_results(_image_result(_IMAGE_URL), str(tmp_path), fetch=fetch)
    second = await media_archive.archive_media_results(_image_result(_IMAGE_URL), str(tmp_path), fetch=fetch)

    assert calls == [_IMAGE_URL]
    assert first.data["workspace_images"] == second.data["workspace_images"]


@pytest.mark.asyncio
async def test_archive_tolerates_download_failure(tmp_path) -> None:
    """单个下载失败只跳过该条，不改写原工具结果。"""
    def fetch(_url: str, _kind: media_archive._MediaKind) -> tuple[bytes, str]:
        raise AppError(ErrorCode.UPSTREAM, "媒体下载失败")

    result = await media_archive.archive_media_results(_image_result(_IMAGE_URL), str(tmp_path), fetch=fetch)

    assert result.data.get("workspace_images") is None
    assert result.data["image_urls"] == [_IMAGE_URL]


@pytest.mark.asyncio
async def test_archive_skips_results_without_media_or_workspace(tmp_path) -> None:
    """失败结果、无媒体链接结果与无工作区上下文都不触发归档。"""
    failed = ToolResult(name="image.generate", ok=False, error={"code": "UPSTREAM"}, call_id="c1")
    assert await media_archive.archive_media_results(failed, str(tmp_path)) is failed

    pending = ToolResult(name="video.status", ok=True, data={"status": "PENDING"}, call_id="c1")
    assert await media_archive.archive_media_results(pending, str(tmp_path)) is pending

    untouched = await media_archive.archive_media_results(_image_result(_IMAGE_URL), "")
    assert untouched.data.get("workspace_images") is None


def test_validate_media_url_rejects_insecure_or_internal_targets(monkeypatch) -> None:
    """仅放行无凭据 HTTPS 公网地址：http、凭据、内网/回环 IP 一律拒绝。"""
    for url in (
        "http://result.example/image.png",
        "https://user:pass@result.example/image.png",
        "https://127.0.0.1/image.png",
        "https://10.0.0.8/image.png",
        "https://[::1]/image.png",
    ):
        with pytest.raises(AppError):
            media_archive._validate_media_url(url)
    # 正向用例的域名解析依赖网络，测试环境用桩替代解析判定。
    monkeypatch.setattr(media_archive, "_reject_internal_target", lambda _host: None)
    assert media_archive._validate_media_url(_IMAGE_URL) == _IMAGE_URL


def test_fetch_media_enforces_content_type_and_size(monkeypatch) -> None:
    """下载层按类别拒绝类型不符与超过上限的响应体。"""
    monkeypatch.setattr(media_archive, "_reject_internal_target", lambda _host: None)

    class _FakeResponse:
        def __init__(self, body: bytes, content_type: str) -> None:
            self._body = body
            message = Message()
            message["Content-Type"] = content_type
            self.headers = message

        def read(self, size: int = -1) -> bytes:
            return self._body if size < 0 else self._body[:size]

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class _FakeOpener:
        def __init__(self, response: _FakeResponse) -> None:
            self._response = response

        def open(self, _request, timeout=None):  # noqa: ANN001,ANN201
            return self._response

    def _install(body: bytes, content_type: str) -> None:
        monkeypatch.setattr(
            media_archive, "build_opener", lambda *_args: _FakeOpener(_FakeResponse(body, content_type))
        )

    _install(b"html", "text/html")
    with pytest.raises(AppError, match="类型"):
        media_archive._fetch_media(_IMAGE_URL, media_archive._IMAGE)

    # 视频类别不接受图片类型，反之亦然（白名单按类别隔离）。
    _install(b"png", "image/png")
    with pytest.raises(AppError, match="类型"):
        media_archive._fetch_media(_VIDEO_URL, media_archive._VIDEO)

    small_image = replace(media_archive._IMAGE, max_bytes=16)
    _install(b"x" * 17, "image/png")
    with pytest.raises(AppError, match="大小"):
        media_archive._fetch_media(_IMAGE_URL, small_image)

    _install(b"x" * 16, "image/png")
    assert media_archive._fetch_media(_IMAGE_URL, small_image) == (b"x" * 16, "image/png")


def _media_tool(name: str) -> ToolDef:
    return ToolDef(
        name=name,
        description="媒体工具",
        parameters_schema={"type": "object", "properties": {"prompt": {"type": "string"}}},
        permission="media.generate",
        timeout_s=5.0,
        handler=lambda *_args, **_kwargs: None,
        output_schema={},
        transport="mcp",
        server_id="media.generation",
        display_name="媒体工具",
        risk_level="network",
    )


def test_manager_archives_media_results_into_sandbox(monkeypatch, tmp_path) -> None:
    """远程媒体结果经 manager 返回前完成工作区归档与字段追加（图片与视频）。"""

    class _FakeMediaProvider(StreamableHttpProvider):
        """仅实现 invoke 的媒体 provider 替身，不建立任何网络会话。"""

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        async def invoke(self, *, tool_id, tool_name, arguments, output_schema, call_id):  # noqa: ANN001
            return ToolResult(name=tool_name, ok=True, data=dict(self._payload), call_id=call_id)

    def _fetch(url: str, kind) -> tuple[bytes, str]:  # noqa: ANN001
        return (b"png-bytes", "image/png") if kind is media_archive._IMAGE else (b"mp4-bytes", "video/mp4")

    monkeypatch.setattr(media_archive, "_fetch_media", _fetch)
    registry = ToolRegistry()
    registry.register(_media_tool("image.generate"))
    registry.register(_media_tool("video.status"))
    context = ToolExecutionContext(sandbox_dir=str(tmp_path), call_id="c-media")

    def _run(payload: dict, tool_id: str, arguments: dict) -> ToolResult:
        manager = MCPClientManager.build_from_registry(
            registry, remote_providers={"media.generation": _FakeMediaProvider(payload)}
        )
        return asyncio.run(manager.call_tool(tool_id, arguments, context))

    image = _run({"status": "succeeded", "image_urls": [_IMAGE_URL]}, "media.generation.image.generate", {"prompt": "一只猫"})
    assert image.ok is True
    image_path = image.data["workspace_images"][0]
    assert (tmp_path / image_path).read_bytes() == b"png-bytes"

    video = _run({"status": "SUCCEEDED", "video_url": _VIDEO_URL}, "media.generation.video.status", {"upstream_task_id": "task-1"})
    assert video.ok is True
    video_path = video.data["workspace_videos"][0]
    assert (tmp_path / video_path).read_bytes() == b"mp4-bytes"
