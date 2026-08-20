"""Qwen Image 客户端单元测试，不调用真实上游。"""

from __future__ import annotations

import base64

import httpx
import pytest

from image_mcp.client import ImageMcpError, QwenImageClient


class _FakeAsyncClient:
    """记录请求并返回预置响应的异步 HTTP 客户端桩。"""

    def __init__(self, response: httpx.Response, image_response: httpx.Response | None = None):
        self.response = response
        self.image_response = image_response
        self.post_calls: list[dict] = []
        self.get_urls: list[str] = []

    async def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self.response

    async def get(self, url: str, **kwargs):
        self.get_urls.append(url)
        if self.image_response is None:
            raise AssertionError("测试未预置图片响应")
        return self.image_response


def _json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    """构造带请求绑定的 httpx 响应。"""
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", "https://test.local"))


def test_client_reads_url_key_and_model_from_environment(monkeypatch):
    """客户端默认读取 .env/进程环境中的 URL、Key 和模型 ID。"""
    monkeypatch.setenv("QWEN_IMAGE_API_URL", "https://env.test/generation")
    monkeypatch.setenv("QWEN_IMAGE_API_KEY", "env-key")
    monkeypatch.setenv("QWEN_IMAGE_MODEL", "qwen-image-3.0")

    client = QwenImageClient()

    assert client.api_url == "https://env.test/generation"
    assert client.api_key == "env-key"
    assert client.model == "qwen-image-3.0"


@pytest.mark.asyncio
async def test_generate_uses_configured_model_and_prompt_extend():
    # 上游 URL 结果会被下载为 MCP image 内容。
    image_url = "https://cdn.example.test/result.png"
    fake = _FakeAsyncClient(
        _json_response(
            {
                "request_id": "req-1",
                "output": {
                    "choices": [{"message": {"content": [{"image": image_url}]}}]
                },
            }
        ),
        httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\nimage",
            headers={"content-type": "image/png"},
            request=httpx.Request("GET", image_url),
        ),
    )
    client = QwenImageClient(
        api_key="test-key",
        api_url="https://test.local/generate",
        model="qwen-image-3.0",
        http_client=fake,
    )

    result = await client.generate("画一只猫", prompt_extend=False)

    body = fake.post_calls[0]["json"]
    assert body["model"] == "qwen-image-3.0"
    assert body["parameters"] == {"prompt_extend": False}
    assert body["input"]["messages"][0]["content"] == [{"text": "画一只猫"}]
    assert fake.post_calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert fake.get_urls == [image_url]
    assert result.data.startswith(b"\x89PNG")
    assert result.mime_type == "image/png"
    assert result.request_id == "req-1"


@pytest.mark.asyncio
async def test_generate_sends_text_and_reference_image():
    """图文输入按 DashScope 多模态 content 数组发送。"""
    image_url = "https://cdn.example.test/reference.png"
    fake = _FakeAsyncClient(
        _json_response(
            {
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [{"image": "https://cdn.example.test/result.png"}]
                            }
                        }
                    ]
                }
            }
        ),
        httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\nresult",
            headers={"content-type": "image/png"},
            request=httpx.Request("GET", "https://cdn.example.test/result.png"),
        ),
    )
    client = QwenImageClient(
        api_key="test-key",
        api_url="https://test.local/generate",
        model="qwen-image-3.0",
        http_client=fake,
    )

    await client.generate("把人物改成油画风格", image=image_url)

    assert fake.post_calls[0]["json"]["input"]["messages"][0]["content"] == [
        {"image": image_url},
        {"text": "把人物改成油画风格"},
    ]


@pytest.mark.asyncio
async def test_generate_supports_base64_content():
    image = b"\xff\xd8\xffjpeg"
    encoded = base64.b64encode(image).decode()
    fake = _FakeAsyncClient(
        _json_response(
            {
                "output": {
                    "choices": [
                        {"message": {"content": [{"b64_json": encoded}]}}
                    ]
                }
            }
        )
    )
    client = QwenImageClient(
        api_key="test-key",
        api_url="https://test.local/generate",
        model="qwen-image-3.0",
        http_client=fake,
    )

    result = await client.generate("test")

    assert result.data == image
    assert result.mime_type == "image/jpeg"
    assert fake.get_urls == []


@pytest.mark.asyncio
async def test_generate_rejects_missing_key_without_http_call():
    fake = _FakeAsyncClient(_json_response({}))
    client = QwenImageClient(api_key="", model="qwen-image-3.0", http_client=fake)

    with pytest.raises(ImageMcpError) as exc_info:
        await client.generate("test")

    assert exc_info.value.code == "CONFIG"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_generate_normalizes_upstream_error():
    fake = _FakeAsyncClient(_json_response({"error": "hidden"}, status_code=401))
    client = QwenImageClient(
        api_key="test-key",
        api_url="https://test.local/generate",
        model="qwen-image-3.0",
        http_client=fake,
    )

    with pytest.raises(ImageMcpError) as exc_info:
        await client.generate("test")

    assert exc_info.value.code == "UPSTREAM"
    assert "hidden" not in str(exc_info.value)
    assert "401" in str(exc_info.value)
