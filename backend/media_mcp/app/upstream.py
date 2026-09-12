"""阿里云百炼媒体上游适配；服务端配置是模型和凭据的唯一来源。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx


class MediaUpstreamError(RuntimeError):
    """上游响应、认证或网络异常的安全归一错误。"""


@dataclass(frozen=True, slots=True)
class MediaSettings:
    """媒体 MCP 的部署期配置；密钥仅从环境读取且从不进入工具结果。"""

    compatible_base_url: str
    api_key: str
    image_model: str
    video_model: str
    request_timeout_s: float

    @classmethod
    def from_env(cls) -> MediaSettings:
        """从受控环境文件与进程环境构造配置，缺少关键项时拒绝计费工具。"""
        values_from_file = _read_config_file()

        def value(name: str, default: str = "") -> str:
            """配置文件优先，允许管理端更新模型而无需重建媒体服务容器。"""
            return values_from_file.get(name, os.getenv(name, default)).strip()

        try:
            request_timeout_s = float(value("MEDIA_MCP_REQUEST_TIMEOUT_SECONDS", "600"))
        except ValueError as exc:
            raise RuntimeError("媒体 MCP 模型或超时配置非法") from exc
        values = cls(
            compatible_base_url=value("MEDIA_MCP_COMPATIBLE_BASE_URL"),
            api_key=value("MEDIA_MCP_API_KEY"),
            image_model=value("MEDIA_MCP_IMAGE_MODEL", "qwen-image-3.0-pro"),
            video_model=value("MEDIA_MCP_VIDEO_MODEL", "happyhorse-1.1-i2v"),
            request_timeout_s=request_timeout_s,
        )
        if not values.compatible_base_url or not values.api_key:
            raise RuntimeError("媒体 MCP 上游地址或凭据未配置")
        if not values.image_model or not values.video_model or values.request_timeout_s <= 0:
            raise RuntimeError("媒体 MCP 模型或超时配置非法")
        return values

    @property
    def origin(self) -> str:
        """从兼容模式 URL 推导同工作空间的异步视频 API 根地址。"""
        parsed = urlsplit(self.compatible_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise RuntimeError("媒体 MCP 上游地址必须是无凭据的 HTTPS 地址")
        if parsed.path.rstrip("/") != "/compatible-mode/v1":
            raise RuntimeError("媒体 MCP 上游地址必须指向 compatible-mode/v1")
        return f"https://{parsed.netloc}"


def _read_config_file() -> dict[str, str]:
    """读取 API 原位更新的 dotenv 文件；格式异常时由环境变量兜底。"""
    config_file = os.getenv("MEDIA_MCP_CONFIG_FILE", "").strip()
    if not config_file:
        return {}
    try:
        lines = Path(config_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        try:
            decoded = json.loads(raw) if raw.startswith('"') else raw
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, str):
            values[key] = decoded
    return values


def _safe_error(response: httpx.Response | None = None) -> MediaUpstreamError:
    """不把上游正文、认证信息或临时链接泄漏到工具调用方。"""
    if response is not None and response.status_code == 401:
        return MediaUpstreamError("媒体上游认证失败")
    return MediaUpstreamError("媒体上游调用失败")


class MediaUpstreamClient:
    """调用 Qwen 生图同步接口和 HappyHorse 视频异步接口。"""

    def __init__(self, settings: MediaSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def _headers(self) -> dict[str, str]:
        """每次请求新建认证头，禁止在日志或返回值中复用。"""
        return {"Authorization": f"Bearer {self._settings.api_key}", "Content-Type": "application/json"}

    async def _request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """有界 HTTP 调用并安全解析 JSON 对象。"""
        headers = {**self._headers, **(extra_headers or {})}
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.request_timeout_s,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(method, url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise MediaUpstreamError("媒体上游连接失败") from exc
        if response.is_error:
            raise _safe_error(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise MediaUpstreamError("媒体上游返回格式异常") from exc
        if not isinstance(data, dict):
            raise MediaUpstreamError("媒体上游返回格式异常")
        return data

    async def generate_image(
        self, *, prompt: str, reference_images: list[str] | None, size: str, count: int,
        prompt_extend: bool,
    ) -> dict[str, Any]:
        """调用兼容模式图片生成接口，返回上游临时图片链接。"""
        payload: dict[str, Any] = {
            "model": self._settings.image_model,
            "prompt": prompt,
            "size": size,
            "n": count,
            "prompt_extend": prompt_extend,
        }
        if reference_images:
            payload["image"] = reference_images[0] if len(reference_images) == 1 else reference_images
        data = await self._request(
            "POST", f"{self._settings.compatible_base_url.rstrip('/')}/images/generations", payload=payload
        )
        images = data.get("data")
        if not isinstance(images, list):
            raise MediaUpstreamError("媒体上游未返回图片结果")
        urls = [item.get("url") for item in images if isinstance(item, dict) and isinstance(item.get("url"), str)]
        if not urls:
            raise MediaUpstreamError("媒体上游未返回图片地址")
        return {"status": "succeeded", "model": self._settings.image_model, "image_urls": urls}

    async def create_video(
        self, *, prompt: str, first_frame: str, resolution: str, duration: int, watermark: bool,
    ) -> dict[str, Any]:
        """提交首帧图生视频任务，只返回可持久化查询的上游任务标识。"""
        data = await self._request(
            "POST",
            f"{self._settings.origin}/api/v1/services/aigc/video-generation/video-synthesis",
            payload={
                "model": self._settings.video_model,
                "input": {"prompt": prompt, "media": [{"type": "first_frame", "url": first_frame}]},
                "parameters": {"resolution": resolution, "duration": duration, "watermark": watermark},
            },
            # HappyHorse 异步任务的服务端契约；没有此头会被上游当作同步请求拒绝。
            extra_headers={"X-DashScope-Async": "enable"},
        )
        output = data.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("task_id"), str):
            raise MediaUpstreamError("媒体上游未返回视频任务标识")
        return {
            "status": str(output.get("task_status") or "PENDING"),
            "model": self._settings.video_model,
            "upstream_task_id": output["task_id"],
        }

    async def get_video(self, *, upstream_task_id: str) -> dict[str, Any]:
        """读取视频任务状态；成功时返回最多 24 小时有效的上游视频地址。"""
        data = await self._request("GET", f"{self._settings.origin}/api/v1/tasks/{upstream_task_id}")
        output = data.get("output")
        if not isinstance(output, dict):
            raise MediaUpstreamError("媒体上游未返回视频任务状态")
        status = output.get("task_status")
        if not isinstance(status, str):
            raise MediaUpstreamError("媒体上游视频任务状态异常")
        result: dict[str, Any] = {"status": status, "upstream_task_id": upstream_task_id}
        if status == "SUCCEEDED" and isinstance(output.get("video_url"), str):
            result["video_url"] = output["video_url"]
        if status == "FAILED":
            result["error_code"] = str(output.get("code") or "UPSTREAM")
        return result
