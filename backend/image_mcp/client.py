"""Qwen Image 3.0 图像生成客户端。

本模块只负责调用阿里云 DashScope 兼容接口并把响应转换成图片二进制，
不依赖 MCP SDK，便于单元测试和后续复用。API Key 只从环境变量或显式
构造参数读取，绝不写入日志、异常消息或仓库文件。
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse

import httpx
from dotenv import load_dotenv

DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_PROMPT_LENGTH = 32_000
MAX_IMAGE_BYTES = 20 * 1024 * 1024

# 优先加载仓库根目录 .env；外部进程已经注入的环境变量不会被覆盖。
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


class ImageMcpError(Exception):
    """图像 MCP 的可控错误，不携带 API Key 或上游响应原文。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ImageResult:
    """生成结果：图片内容、MIME 类型及可选的临时图片地址。"""

    data: bytes
    mime_type: str
    image_url: str | None = None
    request_id: str | None = None

    @property
    def image_format(self) -> str:
        """返回 FastMCP Image 所需的格式名。"""
        return self.mime_type.removeprefix("image/") or "png"


@dataclass(frozen=True)
class _ImageReference:
    """上游响应中的图片引用，可能是 URL 或 Base64。"""

    value: str
    kind: str
    mime_type: str | None = None


def _as_image_reference(item: object) -> _ImageReference | None:
    """从一个 content 块中提取 URL、data URI 或 Base64 图片引用。"""
    if not isinstance(item, dict):
        return None

    for key in ("image", "image_url", "url"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("image_url")
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            return _ImageReference(
                value=normalized,
                kind="data_uri" if normalized.startswith("data:") else "url",
            )

    value = item.get("b64_json")
    if isinstance(value, str) and value.strip():
        return _ImageReference(value=value.strip(), kind="base64", mime_type="image/png")
    return None


def _extract_image_reference(payload: object) -> _ImageReference:
    """兼容 Qwen Image 常见响应形状，提取第一张生成图片。"""
    if not isinstance(payload, dict):
        raise ImageMcpError("UPSTREAM", "上游响应结构异常")

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

        # 兼容部分网关把图片直接放在 output.image / output.url 下。
        direct = _as_image_reference(output)
        if direct:
            return direct

    # 兼容 OpenAI 风格的 data 数组，便于替换同类图像网关。
    data_items = payload.get("data")
    if isinstance(data_items, list):
        for item in data_items:
            reference = _as_image_reference(item)
            if reference:
                return reference

    raise ImageMcpError("UPSTREAM", "上游未返回图片")


def _decode_data_uri(value: str) -> tuple[bytes, str]:
    """解码 data URI 图片。"""
    try:
        header, encoded = value.split(",", 1)
        if not header.startswith("data:"):
            raise ValueError
        mime_type = header[5:].split(";", 1)[0] or "image/png"
        data = (
            base64.b64decode(encoded, validate=True)
            if ";base64" in header
            else unquote_to_bytes(encoded)
        )
    except (ValueError, binascii.Error) as exc:
        raise ImageMcpError("UPSTREAM", "上游图片数据无法解析") from exc
    return data, mime_type


def _decode_base64(value: str, mime_type: str = "image/png") -> tuple[bytes, str]:
    """解码响应中的 Base64 图片。"""
    try:
        return base64.b64decode(value, validate=True), mime_type
    except (ValueError, binascii.Error) as exc:
        raise ImageMcpError("UPSTREAM", "上游图片数据无法解析") from exc


def _sniff_image_mime(data: bytes, fallback: str = "image/png") -> str:
    """根据少量文件头识别常见图片类型，避免错误标记为 PNG。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback if fallback.startswith("image/") else "image/png"


def _validate_image(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """校验图片大小并规范 MIME 类型。"""
    if not data:
        raise ImageMcpError("UPSTREAM", "上游返回空图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageMcpError("UPSTREAM", "生成图片超过 20MB 限制")
    return data, _sniff_image_mime(data, mime_type)


class QwenImageClient:
    """调用 Qwen Image 3.0 多模态生成接口。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """初始化客户端；未显式传参时从仓库根目录 .env 读取配置。"""
        configured_key = api_key
        if configured_key is None:
            # 兼容用户 curl 示例中的 DASHSCOPE_API_KEY，同时优先使用 MCP 专用变量。
            configured_key = os.getenv("QWEN_IMAGE_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
        self.api_key = configured_key.strip()
        self.api_url = (api_url if api_url is not None else os.getenv("QWEN_IMAGE_API_URL", "")).strip()
        self.model = (model if model is not None else os.getenv("QWEN_IMAGE_MODEL", "")).strip()
        timeout_value = timeout_seconds
        if timeout_value is None:
            raw_timeout = os.getenv("QWEN_IMAGE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
            try:
                timeout_value = float(raw_timeout)
            except ValueError as exc:
                raise ImageMcpError("CONFIG", "QWEN_IMAGE_TIMEOUT_SECONDS 配置无效") from exc
        if timeout_value <= 0:
            raise ImageMcpError("CONFIG", "QWEN_IMAGE_TIMEOUT_SECONDS 必须大于 0")
        self.timeout_seconds = timeout_value
        self.http_client = http_client

    async def generate(
        self,
        prompt: str,
        *,
        image: str | None = None,
        prompt_extend: bool = True,
    ) -> ImageResult:
        """提交文本或文本+图像生成请求，并下载结果图片。"""
        self._validate_prompt(prompt)
        if not self.api_key:
            raise ImageMcpError("CONFIG", "未配置 QWEN_IMAGE_API_KEY")
        if not self.api_url:
            raise ImageMcpError("CONFIG", "未配置 QWEN_IMAGE_API_URL")
        if not self.model:
            raise ImageMcpError("CONFIG", "未配置 QWEN_IMAGE_MODEL")

        content: list[dict[str, str]] = []
        if image is not None:
            content.append({"image": self._normalize_input_image(image)})
        content.append({"text": prompt})

        request_body = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": {"prompt_extend": prompt_extend},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        if self.http_client is not None:
            return await self._generate_with_client(self.http_client, request_body, headers)

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await self._generate_with_client(client, request_body, headers)

    async def _generate_with_client(
        self,
        client: httpx.AsyncClient,
        request_body: dict,
        headers: dict[str, str],
    ) -> ImageResult:
        """使用给定 HTTP 客户端完成请求和图片下载，便于测试注入桩客户端。"""
        try:
            response = await client.post(self.api_url, json=request_body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ImageMcpError("TIMEOUT", "图像生成上游调用超时") from exc
        except httpx.HTTPStatusError as exc:
            raise ImageMcpError("UPSTREAM", f"图像生成上游返回 HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ImageMcpError("UPSTREAM", "图像生成上游连接失败") from exc
        except ValueError as exc:
            raise ImageMcpError("UPSTREAM", "图像生成上游响应不是有效 JSON") from exc

        reference = _extract_image_reference(payload)
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        if not isinstance(request_id, str):
            request_id = None

        if reference.kind == "data_uri":
            data, mime_type = _decode_data_uri(reference.value)
            data, mime_type = _validate_image(data, mime_type)
            return ImageResult(data=data, mime_type=mime_type, request_id=request_id)
        if reference.kind == "base64":
            data, mime_type = _decode_base64(reference.value, reference.mime_type or "image/png")
            data, mime_type = _validate_image(data, mime_type)
            return ImageResult(data=data, mime_type=mime_type, request_id=request_id)

        data, mime_type = await self._download_image(client, reference.value)
        data, mime_type = _validate_image(data, mime_type)
        return ImageResult(
            data=data,
            mime_type=mime_type,
            image_url=reference.value,
            request_id=request_id,
        )

    async def _download_image(self, client: httpx.AsyncClient, image_url: str) -> tuple[bytes, str]:
        """下载上游临时图片 URL，并拒绝非 HTTP(S) 地址。"""
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ImageMcpError("UPSTREAM", "上游返回的图片地址无效")
        try:
            response = await client.get(image_url)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ImageMcpError("TIMEOUT", "图片下载上游调用超时") from exc
        except httpx.HTTPStatusError as exc:
            raise ImageMcpError("UPSTREAM", f"图片下载上游返回 HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ImageMcpError("UPSTREAM", "图片下载上游连接失败") from exc

        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return response.content, content_type

    @staticmethod
    def _validate_prompt(prompt: str) -> None:
        """校验必填提示词，防止空请求和异常超长请求。"""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ImageMcpError("VALIDATION", "prompt 不能为空")
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise ImageMcpError("VALIDATION", "prompt 不能超过 32000 个字符")

    @staticmethod
    def _normalize_input_image(image: str) -> str:
        """规范化图片输入为上游支持的公网 URL 或 Data URI。"""
        if not isinstance(image, str) or not image.strip():
            raise ImageMcpError("VALIDATION", "image 不能为空")
        value = image.strip()
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
        if value.startswith("data:"):
            try:
                data, mime_type = _decode_data_uri(value)
            except ImageMcpError:
                raise
            if not mime_type.startswith("image/"):
                raise ImageMcpError("VALIDATION", "image 必须是图片 Data URI")
            _validate_image(data, mime_type)
            return value
        if parsed.scheme:
            raise ImageMcpError("VALIDATION", "image 只支持 HTTP(S) URL、Data URI 或本地图片路径")

        try:
            path = Path(value).expanduser()
            if not path.is_file():
                raise ImageMcpError("VALIDATION", "本地 image 文件不存在")
            mime_type, _ = mimetypes.guess_type(path.name)
            if not mime_type or not mime_type.startswith("image/"):
                raise ImageMcpError("VALIDATION", "本地 image 文件必须是图片格式")
            data, detected_mime = _validate_image(path.read_bytes(), mime_type)
        except ImageMcpError:
            raise
        except (OSError, ValueError) as exc:
            raise ImageMcpError("VALIDATION", "本地 image 文件无法读取") from exc
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{detected_mime};base64,{encoded}"
