"""最小 MCP 注册表的回归测试。"""

from app.agent.mcp_registry import REGISTERED_TOOLS, get_tool_definition


def test_registered_tools_only_keep_multimedia_capabilities():
    """业务工具移除后，注册表只能暴露多媒体能力。"""
    assert [tool.name for tool in REGISTERED_TOOLS] == [
        "audio.voiceclone",
        "image.generate",
        "audio.speech_recognition",
        "audio.speech_synthesis",
    ]
    assert all(tool.permission == "write" and tool.timeout_s == 90 for tool in REGISTERED_TOOLS)


def test_unregistered_business_tool_cannot_be_resolved():
    """旧业务工具不能绕过注册表进入 ToolCall 分派。"""
    assert get_tool_definition("model.list") is None
    assert get_tool_definition("dataset.list") is None
    assert get_tool_definition("image.generate").title == "Qwen Image 生图"
