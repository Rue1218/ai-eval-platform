"""阶段 1 Parser：Schema 拒绝多余字段，产品裁剪保持现网语义。"""

from __future__ import annotations

import pytest

from app.harness.orchestration.parser import tool_call_from_step, validate_react_output
from app.harness.orchestration.react_adapter import parse_mcp_step


def test_schema_rejects_model_supplied_trace_id():
    """模型 JSON 不得自带 trace_id。"""
    with pytest.raises(ValueError, match="禁止字段"):
        validate_react_output(
            {
                "thought": "先想",
                "tool": "image.generate",
                "arguments": {},
                "done": False,
                "trace_id": "T-forged",
            }
        )


def test_schema_requires_thought_tool_arguments_done():
    """缺必填字段不得进入执行。"""
    with pytest.raises(ValueError, match="缺少字段"):
        validate_react_output({"tool": "image.generate", "arguments": {}, "done": False})


def test_parse_mcp_step_still_accepts_partial_product_dict():
    """产品适配入口保持现网宽松 dict，不把 Schema 套到单测桩。"""
    step = parse_mcp_step({"tool": "image.generate", "arguments": {}, "done": False})
    assert step.tool == "image.generate"
    call = tool_call_from_step(step)
    assert call.trace_id is None
    assert call.span_id is None
