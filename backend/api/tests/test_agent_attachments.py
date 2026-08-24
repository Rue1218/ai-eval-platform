"""Agent 附件进入模型上下文的单元测试。"""

from pathlib import Path
from types import SimpleNamespace

from app.adapters import _adapt_message_content
from app.agent.attachments import build_model_content, stage_attachments


def _stored(tmp_path: Path, filename: str, content: bytes, content_type: str, file_id: str = "file-test"):
    """构造带临时二进制路径的最小文件实体。"""
    path = tmp_path / filename
    path.write_bytes(content)
    return SimpleNamespace(
        id=file_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=str(path),
    )


def test_text_attachment_lazy_read_manifest(tmp_path: Path) -> None:
    """有工作区时 txt/md 附件输出路径清单，正文留给 read 工具懒读取。"""
    stored = _stored(tmp_path, "brief.md", "# 评测目标\n比较两个模型。".encode(), "text/markdown")

    result = build_model_content("请总结附件", [stored], workspace_dir=str(tmp_path / "ws"))

    assert isinstance(result, str)
    assert "请总结附件" in result
    assert "brief.md" in result
    assert f"attachments/{stored.id}-brief.md" in result
    assert "read" in result
    assert "比较两个模型" not in result  # 正文不再内联，留给 read 工具读取


def test_text_attachment_inline_fallback_without_workspace(tmp_path: Path) -> None:
    """无工作区（历史/离线上下文）时回退内联注入，兼容旧行为。"""
    stored = _stored(tmp_path, "brief.md", "# 评测目标\n比较两个模型。".encode(), "text/markdown")

    result = build_model_content("请总结附件", [stored])

    assert isinstance(result, str)
    assert "请总结附件" in result
    assert "比较两个模型" in result


def test_stage_attachments_path_matches_manifest(tmp_path: Path, monkeypatch) -> None:
    """txt/md staging 落在 {workspace}/attachments/{file_id}-{name}，且与清单路径一致。

    回归：曾把带 attachments/ 前缀的路径再次 join 到 attach_dir 上，产生
    attachments/attachments/{file_id}-{name} 双重前缀，os.link/copyfile 均
    因父目录缺失抛 FileNotFoundError，整轮 Agent 挂掉。
    """
    session_id = "b68eddc9-2b37-4883-b90c-3756035fbc5e"
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    stored = _stored(tmp_path, "brief.md", "正文内容".encode(), "text/markdown", file_id="file-abc")

    stage_attachments(session_id, [stored])

    staged = tmp_path / "ws" / session_id / "attachments" / "file-abc-brief.md"
    assert staged.is_file()
    assert staged.read_text(encoding="utf-8") == "正文内容"
    # 清单相对路径必须与 staging 目标一致（read 工具按沙箱根解析）
    result = build_model_content("分析", [stored], workspace_dir=str(tmp_path / "ws" / session_id))
    assert "attachments/file-abc-brief.md" in result


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
