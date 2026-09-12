"""媒体上游协议测试：不触网、不调用计费模型。"""

from __future__ import annotations

import httpx
import pytest

from app.upstream import MediaSettings, MediaUpstreamClient, MediaUpstreamError


def _settings() -> MediaSettings:
    """构造不含真实凭据的测试配置。"""
    return MediaSettings(
        compatible_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        api_key="test-key",
        image_model="qwen-image-3.0-pro",
        video_model="happyhorse-1.1-i2v",
        request_timeout_s=1,
    )


@pytest.mark.asyncio
async def test_generate_image_uses_compatible_endpoint_and_does_not_expose_key() -> None:
    """生图保持兼容模式 URL，认证只放 HTTP 请求头。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"data": [{"url": "https://result.example/image.png"}]})

    client = MediaUpstreamClient(_settings(), transport=httpx.MockTransport(handler))
    result = await client.generate_image(
        prompt="一朵花", reference_images=None, size="1024x1024", count=1, prompt_extend=True
    )

    assert seen["url"].endswith("/compatible-mode/v1/images/generations")
    assert seen["auth"] == "Bearer test-key"
    assert "test-key" not in seen["body"]
    assert result["image_urls"] == ["https://result.example/image.png"]


@pytest.mark.asyncio
async def test_video_create_and_status_use_async_dashscope_paths() -> None:
    """视频创建和查询分离，路径均由同一工作空间域名派生。"""
    urls: list[str] = []
    async_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.method == "POST":
            async_headers.append(request.headers.get("X-DashScope-Async"))
            return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
        return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED", "video_url": "https://result.example/video.mp4"}})

    client = MediaUpstreamClient(_settings(), transport=httpx.MockTransport(handler))
    created = await client.create_video(
        prompt="让花朵轻轻摇摆", first_frame="https://images.example/frame.png", resolution="720P",
        duration=5, watermark=True,
    )
    status = await client.get_video(upstream_task_id="task-1")

    assert created == {"status": "PENDING", "model": "happyhorse-1.1-i2v", "upstream_task_id": "task-1"}
    assert status["video_url"] == "https://result.example/video.mp4"
    assert urls == [
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-1",
    ]
    assert async_headers == ["enable"]


@pytest.mark.asyncio
async def test_upstream_error_is_safely_normalized() -> None:
    """上游响应正文不透传，认证失败只给稳定错误。"""
    client = MediaUpstreamClient(
        _settings(), transport=httpx.MockTransport(lambda request: httpx.Response(401, text="secret upstream body"))
    )
    with pytest.raises(MediaUpstreamError, match="认证失败"):
        await client.get_video(upstream_task_id="task-1")
