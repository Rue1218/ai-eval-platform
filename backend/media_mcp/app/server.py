"""Streamable HTTP 媒体 MCP：生图同步返回，视频仅创建及查询异步任务。"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .upstream import MediaSettings, MediaUpstreamClient, MediaUpstreamError

_SIZE_PATTERN = re.compile(r"[0-9]{1,5}[x*][0-9]{1,5}")


def _require_prompt(value: str) -> str:
    """统一限制提示词，避免空请求和异常长的上游输入。"""
    prompt = value.strip()
    if not prompt or len(prompt) > 5000:
        raise ValueError("prompt 必须为 1–5000 个字符")
    return prompt


def _validate_media(value: str) -> str:
    """仅允许 HTTPS 公网地址或受上限保护的图片 Data URI。"""
    media = value.strip()
    if media.startswith("data:image/") and ";base64," in media and len(media) <= 28 * 1024 * 1024:
        return media
    parsed = urlsplit(media)
    if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
        return media
    raise ValueError("参考图片必须是 HTTPS 地址或不超过 20MB 的图片 Data URI")


mcp = FastMCP(
    "AI Eval Media MCP",
    instructions="提供 Qwen 图片生成和 HappyHorse 首帧图生视频。视频创建后必须使用 video.status 查询结果。",
    host="0.0.0.0",
    port=8002,
    streamable_http_path="/mcp",
    json_response=True,
)


def _client() -> MediaUpstreamClient:
    """每次调用读取受控配置文件，使管理端模型更新无需重启服务。"""
    return MediaUpstreamClient(MediaSettings.from_env())


class MediaToolResponse(BaseModel):
    """三个媒体工具共用的结构化返回，避免动态字典失去 MCP 输出契约。"""

    status: str
    model: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    upstream_task_id: str | None = None
    video_url: str | None = None
    code: str | None = None
    message: str | None = None
    error_code: str | None = None


@mcp.tool(name="image.generate", title="生成图片", structured_output=True)
async def generate_image(
    prompt: str,
    reference_images: list[str] | None = None,
    size: str = "1024x1024",
    count: int = 1,
    prompt_extend: bool = True,
) -> MediaToolResponse:
    """使用 Qwen Image 3.0 Pro 生成图片；参考图最多三张。"""
    if not 1 <= count <= 6:
        raise ValueError("count 必须为 1–6")
    if len(size) > 32 or not _SIZE_PATTERN.fullmatch(size.strip()):
        raise ValueError("size 必须为宽x高格式，例如 1024x1024")
    images = [_validate_media(item) for item in reference_images or []]
    if len(images) > 3:
        raise ValueError("reference_images 最多三张")
    try:
        return MediaToolResponse(**await _client().generate_image(
            prompt=_require_prompt(prompt), reference_images=images or None, size=size, count=count,
            prompt_extend=prompt_extend,
        ))
    except MediaUpstreamError as exc:
        return MediaToolResponse(status="failed", code="UPSTREAM", message=str(exc))


@mcp.tool(name="video.create", title="创建图生视频", structured_output=True)
async def create_video(
    prompt: str,
    first_frame: str,
    resolution: str = "1080P",
    duration: int = 5,
    watermark: bool = True,
) -> MediaToolResponse:
    """使用 HappyHorse 首帧图生视频；返回任务 ID，不等待数分钟的生成过程。"""
    if resolution not in {"480P", "720P", "1080P"}:
        raise ValueError("resolution 仅支持 480P、720P、1080P")
    if not 3 <= duration <= 15:
        raise ValueError("duration 必须为 3–15 秒")
    try:
        return MediaToolResponse(**await _client().create_video(
            prompt=_require_prompt(prompt), first_frame=_validate_media(first_frame), resolution=resolution,
            duration=duration, watermark=watermark,
        ))
    except MediaUpstreamError as exc:
        return MediaToolResponse(status="failed", code="UPSTREAM", message=str(exc))


@mcp.tool(name="video.status", title="查询视频任务", structured_output=True)
async def get_video_status(upstream_task_id: str) -> MediaToolResponse:
    """查询已提交视频任务；成功后的临时视频地址应尽快由平台归档。"""
    task_id = upstream_task_id.strip()
    if not task_id or len(task_id) > 200:
        raise ValueError("upstream_task_id 非法")
    try:
        return MediaToolResponse(**await _client().get_video(upstream_task_id=task_id))
    except MediaUpstreamError as exc:
        return MediaToolResponse(status="failed", code="UPSTREAM", message=str(exc))


app = mcp.streamable_http_app()
