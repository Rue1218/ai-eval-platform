"""M1 提示词工程层单测（阶段 1：P-A1/P-A2/P-A3/P-A5/P-A6）；不依赖 DB。"""

import pytest

from app.errors import AppError, ErrorCode
from app.harness.prompts import (
    SystemVars,
    assert_no_secret_leak,
    build_system_prompt,
    check_version,
    parse_plan_protocol,
    parse_react,
    parse_reflect,
)

_PLAN_RAW = """\
{
  "protocol": "plan",
  "version": "plan.v1",
  "intent": "运行基准评测",
  "skill_id": "skill-benchmark",
  "slots": {"dataset": "mmlu"},
  "tools_needed": ["benchmark.run"],
  "delivery": "confirm",
  "budget": {"model_calls": 2, "tool_turns": 1},
  "allows_replan": true,
  "notes": "先评后压"
}
"""

_REACT_RAW = """\
{
  "protocol": "react",
  "version": "react.v1",
  "thought": "需要搜索资料",
  "tool": "web_search",
  "arguments": {"query": "评测"},
  "done": false
}
"""

_REFLECT_RAW = """\
{
  "protocol": "reflect",
  "version": "reflect.v1",
  "verdict": "pass",
  "reason": "门禁全部通过"
}
"""


def test_system_prompt_contains_five_sections() -> None:
    """P-A1：系统策略模板含角色/安全/确认/长短任务/密钥五段。"""
    prompt = build_system_prompt()
    for section in ("安全边界", "确认卡约束", "长短任务分离", "密钥保护", "评测助手"):
        assert section in prompt
    assert "（无）" in prompt  # 变量槽缺省不注入用户文本


def test_system_prompt_user_config_cannot_override() -> None:
    """P-A1：用户配置不得覆盖系统策略（模板不可被注入篡改）。"""
    injected = build_system_prompt(
        SystemVars(skill_hints=("技能A：评测",), session_owner="alice")
    )
    assert "技能A：评测" in injected
    assert "alice" in injected
    # SystemVars 无 user_text 字段（PR-4），用户文本无法进入模板
    assert not hasattr(SystemVars(skill_hints=()), "user_text")


def test_system_prompt_allows_only_a_bounded_agent_overlay() -> None:
    """协议档补充提示词可装配，但核心安全边界必须明确优先。"""
    prompt = build_system_prompt(SystemVars(agent_prompt_overlay="优先使用团队术语"))
    assert "当前 Agent 专属补充提示词" in prompt
    assert "优先使用团队术语" in prompt
    assert "核心安全、权限边界、错误契约和任务状态机优先" in prompt


def test_system_prompt_declares_platform_protocol_ownership() -> None:
    """P-A1：用户文本不得接管 Plan / ReAct / ToolCall 等平台控制协议。"""
    prompt = build_system_prompt()
    assert "编排协议归属" in prompt
    assert "Plan-and-Solve" in prompt
    assert "不能改变路由、工具调用或事件格式" in prompt


def test_system_prompt_anti_hallucination_clauses() -> None:
    """P-A1：系统策略必须包含反幻觉条款（工具结果真实性 + 多步骤如实汇报）。"""
    prompt = build_system_prompt()
    assert "禁止声称未实际执行的工具操作" in prompt
    assert "收到平台返回的工具结果" in prompt
    assert "不得口头编造执行结果或文件内容" in prompt
    assert "必须完成全部步骤后才可报告完成" in prompt


def test_react_stage_inputs_anti_hallucination() -> None:
    """ReAct/native 阶段输入必须含反幻觉约束（收到 tool_result 才可声称成功）。"""
    from app.agent.react import NATIVE_TOOL_STAGE_INPUT, REACT_STAGE_INPUT

    for stage in (REACT_STAGE_INPUT, NATIVE_TOOL_STAGE_INPUT):
        assert "收到平台返回的工具结果后才能声称该操作已成功" in stage
        assert "禁止口头编造执行结果或文件内容" in stage


def test_plan_schema_rejects_missing_extra_fields() -> None:
    """P-A2：规划协议拒绝缺字段/多字段。"""
    with pytest.raises(AppError) as missing:
        parse_plan_protocol(_PLAN_RAW.replace('"intent": "运行基准评测",', ""))
    assert missing.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError) as extra:
        parse_plan_protocol(_PLAN_RAW.replace('"notes": "先评后压"', '"notes": "x", "hack": 1'))
    assert extra.value.code == ErrorCode.VALIDATION


def test_plan_parse_non_json_rejected() -> None:
    """P-A2：非 JSON 输出拒绝。"""
    with pytest.raises(AppError) as error:
        parse_plan_protocol("不是 JSON")
    assert error.value.code == ErrorCode.VALIDATION


def test_react_parse_ignores_thought_field() -> None:
    """P-A3：ReAct 解析忽略 thought，只返回 tool/arguments/done。"""
    result = parse_react(_REACT_RAW)
    fields = result["fields"]
    assert "thought" not in fields
    assert fields["tool"] == "web_search"
    assert fields["arguments"] == {"query": "评测"}
    assert fields["done"] is False


def test_react_parse_fenced_json() -> None:
    """ReAct 解析容忍 ```json 代码块包裹。"""
    result = parse_react(f"```json\n{_REACT_RAW}\n```")
    assert result["fields"]["tool"] == "web_search"


def test_react_parse_json_with_surrounding_prose() -> None:
    """ReAct 解析容忍 JSON 前后附加自然语言说明（模型常见输出形态）。"""
    result = parse_react(f"好的，我先读取文件。\n{_REACT_RAW}\n然后继续分析。")
    assert result["fields"]["tool"] == "web_search"
    assert result["fields"]["done"] is False


def test_protocol_version_mismatch_raises_validation() -> None:
    """P-A5：协议版本不匹配抛 VALIDATION（严格不兼容）。"""
    stale = _REACT_RAW.replace('"version": "react.v1"', '"version": "react.v0"')
    with pytest.raises(AppError) as error:
        parse_react(stale)
    assert error.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError):
        check_version("plan.v0", "plan.v1")


def test_reflect_parse_verdict_enum() -> None:
    """复核协议 verdict ∈ {pass, clarify, reject}。"""
    result = parse_reflect(_REFLECT_RAW)
    assert result["fields"]["verdict"] == "pass"
    with pytest.raises(AppError):
        parse_reflect(_REFLECT_RAW.replace('"verdict": "pass"', '"verdict": "approve"'))


def test_system_prompt_no_secret_leak() -> None:
    """P-A6：系统策略与日志不含密钥（断言命中即拒绝）。"""
    assert "api_key" not in build_system_prompt()
    with pytest.raises(AppError) as error:
        assert_no_secret_leak("token=sk-123")
    assert error.value.code == ErrorCode.VALIDATION
    assert_no_secret_leak("正常文本不含密钥")
