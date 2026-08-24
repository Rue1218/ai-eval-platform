"""Agent 附件进入模型上下文的单元测试。"""

from pathlib import Path
from types import SimpleNamespace

from app.adapters import _adapt_message_content
from app.agent.attachments import build_model_content


def _stored(tmp_path: Path, filename: str, content: bytes, content_type: str):
    """构造带临时二进制路径的最小文件实体。"""
    path = tmp_path / filename
    path.write_bytes(content)
    return SimpleNamespace(
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=str(path),
    )


def test_text_attachment_is_injected_into_model_content(tmp_path: Path) -> None:
    """Markdown 正文应和用户提示词一起进入模型内容。"""
    stored = _stored(tmp_path, "brief.md", "# 评测目标\n比较两个模型。".encode(), "text/markdown")

    result = build_model_content("请总结附件", [stored])

    assert isinstance(result, str)
    assert "请总结附件" in result
    assert "brief.md" in result
    assert "比较两个模型" in result


def test_image_attachment_is_projected_as_internal_image_part(tmp_path: Path) -> None:
    """图片附件应保留图片内容块，供三协议适配器转换后发送给视觉模型。"""
    stored = _stored(tmp_path, "screen.png", b"\x89PNG\r\n", "image/png")

    result = build_model_content("识别图片", [stored])

    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": result[0]["text"]}
    assert result[0]["text"].startswith("识别图片")
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_image_parts_are_adapted_for_anthropic_and_responses() -> None:
    """内部图片块应映射为 Anthropic 与 Responses 各自的内容结构。"""
    content = [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}},
    ]

    anthropic = _adapt_message_content(content, "anthropic_messages")
    responses = _adapt_message_content(content, "openai_responses")

    assert anthropic[0] == {"type": "text", "text": "看图"}
    assert anthropic[1]["type"] == "image"
    assert anthropic[1]["source"]["data"] == "ZmFrZQ=="
    assert responses[0] == {"type": "input_text", "text": "看图"}
    assert responses[1] == {"type": "input_image", "image_url": "data:image/png;base64,ZmFrZQ=="}
