"""M2 上下文工程层单测（X-A1~X-A7）；不依赖 DB。"""

import pytest

from app.errors import AppError
from app.harness.context import (
    COMPACT_VERSION,
    WindowMessage,
    assemble,
    compact_summary_from_configurable,
    compute_meter,
    estimate_tokens,
    is_window_eligible,
    parse_compact,
    project_meter,
    recent_window,
    select_tool_defs,
    skill_hint_lines,
    summarize,
    to_observation,
    truncate_with_marker,
)
from app.harness.contracts import Observation
from app.harness.execution import build_default_registry


def _messages(count: int) -> list[WindowMessage]:
    """构造 count 条 user/assistant 交替消息（source_id 自增）。"""
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"消息-{index}",
            "source_id": f"message:{index}",
        }
        for index in range(count)
    ]


def test_recent_window_default_20_tail() -> None:
    """X-A1：recent_window 默认取末尾 20 条。"""
    window = recent_window(_messages(50))
    assert len(window) == 20
    assert window[0]["content"] == "消息-30"
    assert window[-1]["content"] == "消息-49"


def test_recent_window_compact_keep_from_truncates() -> None:
    """X-A1：compact_keep_from 指定保留起点时截断更早消息。"""
    window = recent_window(_messages(50), keep_from="message:35")
    assert window[0]["content"] == "消息-35"
    assert len(window) == 15


def test_recent_window_keep_from_missing_ignored() -> None:
    """X-A1：keep_from 未命中时忽略，回退末尾 limit。"""
    window = recent_window(_messages(10), keep_from="message:999")
    assert len(window) == 10


def test_window_filters_non_user_assistant() -> None:
    """X-A2：窗口只含 user/assistant，事件（thought/tool/confirm）被过滤。"""
    assert is_window_eligible("user") is True
    assert is_window_eligible("assistant") is True
    assert is_window_eligible("thought") is False
    assert is_window_eligible("tool_call") is False
    assert is_window_eligible("confirm") is False
    assert is_window_eligible("progress") is False
    mixed: list[WindowMessage] = [
        {"role": "thought", "content": "规划", "source_id": "e1"},
        {"role": "user", "content": "你好", "source_id": "m1"},
        {"role": "tool_call", "content": "read", "source_id": "e2"},
        {"role": "assistant", "content": "收到", "source_id": "m2"},
    ]
    window = recent_window(mixed)
    assert [item["role"] for item in window] == ["user", "assistant"]


def test_assemble_order_persona_skill_summary_stage_messages() -> None:
    """X-A4：装配顺序 Persona → Skill Hint → 工作流 → 摘要 → 阶段输入 → 消息。"""
    result = assemble(
        system="【Persona】评测助手",
        skill_hints=("技能A：基准评测",),
        skill_workflow="三协议调用、规则评分",
        summary="已评测 mmlu",
        stage_input="请输出规划 JSON",
        messages=[{"role": "user", "content": "你好"}],
    )
    system = result["system"]
    persona_index = system.index("【Persona】")
    skill_index = system.index("技能A")
    workflow_index = system.index("三协议调用")
    summary_index = system.index("已评测 mmlu")
    stage_index = system.index("请输出规划 JSON")
    assert persona_index < skill_index < workflow_index < summary_index < stage_index
    assert result["messages"] == [{"role": "user", "content": "你好"}]
    assert result["tools"] == []


def test_assemble_omits_empty_sections() -> None:
    """X-A4：空的可选段不占位。"""
    result = assemble(system="【Persona】", messages=[{"role": "user", "content": "hi"}])
    assert result["system"] == "【Persona】"


def test_select_tool_defs_unregistered_excluded() -> None:
    """X-A5：未注册工具名不注入。"""

    class _StubRegistry:
        def get_def(self, name: str):
            return {"name": "read"} if name == "read" else None

    definitions = select_tool_defs(
        _StubRegistry(), mode="react", tools_needed=("read", "not_exist")
    )
    assert [item["name"] for item in definitions] == ["read"]


def test_select_tool_defs_chat_returns_empty() -> None:
    """X-A5：Chat 路径不注入任何工具定义。"""

    class _StubRegistry:
        def get_def(self, name: str):
            return {"name": name}

    assert select_tool_defs(_StubRegistry(), mode="chat", tools_needed=("read",)) == []
    assert select_tool_defs(_StubRegistry(), mode="direct", tools_needed=("read",)) == []


def test_select_tool_defs_react_native_excludes_mcp() -> None:
    """CX-5：ReAct 默认只注入短原生工具，不默认注入 MCP 长工具。"""
    names = {item["name"] for item in select_tool_defs(build_default_registry(), mode="react")}
    assert {"read", "write", "edit", "bash", "task"} <= names
    assert "task.create" not in names
    assert "task.status" not in names
    named = {
        item["name"]
        for item in select_tool_defs(
            build_default_registry(), mode="react", tools_needed=("task.create",)
        )
    }
    assert "task.create" in named
    assert "read" in named
    planned = {
        item["name"]
        for item in select_tool_defs(
            build_default_registry(),
            mode="react",
            tools_needed=("read",),
            planned_only=True,
        )
    }
    assert planned == {"read"}


def test_skill_hint_lines_are_catalog_directory() -> None:
    """SK-1：常驻 Skill Hint 为名称 + 一句话，不含完整工作流。"""
    lines = skill_hint_lines()
    assert any("基准评测" in line for line in lines)
    assert all("：" in line for line in lines)


def test_compact_summary_from_configurable() -> None:
    """assemble 从 configurable.session 读取 compact 摘要。"""
    assert compact_summary_from_configurable({"session": {"compact_summary": " 已压缩 "}}) == "已压缩"
    assert compact_summary_from_configurable({"session": {"compact_summary": ""}}) is None
    assert compact_summary_from_configurable({}) is None


def test_assemble_injects_tool_defs() -> None:
    """X-4：按本轮最小注入工具定义（tools 透传）。"""
    result = assemble(
        system="【Persona】",
        messages=[{"role": "user", "content": "hi"}],
        tool_defs=[{"name": "web_search", "description": "搜索"}],
    )
    assert result["tools"] == [{"name": "web_search", "description": "搜索"}]


def test_truncate_with_marker_keeps_head_and_tail() -> None:
    """X-D2：超长截断保留头尾，并带截断标记。"""
    text = "HEAD" + ("x" * 80) + "TAIL"
    clipped, truncated = truncate_with_marker(text, max_chars=20)
    assert truncated is True
    assert clipped.startswith("HEAD")
    assert clipped.endswith("TAIL")
    assert "[截断]" in clipped


def test_to_observation_redacts_and_truncates_with_source() -> None:
    """X-A3：observation 摘要先脱敏再截断，带 truncated 与 source 溯源。"""
    observation = Observation(
        tool="web_fetch",
        text="http://example.com " + "x" * 3000,
        ok=True,
        truncated=False,
        source="message:abc",
    )
    line = to_observation(observation, max_chars=100)
    assert "[截断]" in line
    assert "来源：message:abc" in line
    assert len(line) < 200


def test_to_observation_marks_ok_and_failed() -> None:
    """observation 摘要携带 ok 标记。"""
    ok = to_observation(Observation(tool="read", text="内容", ok=True))
    failed = to_observation(Observation(tool="read", text="失败", ok=False))
    assert ok.startswith("✅")
    assert failed.startswith("⚠️")
    assert "[read]" in ok


def test_to_observation_appends_repair_hint() -> None:
    """失败 Observation 的 repair_hint 注入模型摘要，不单独当正文。"""
    line = to_observation(
        Observation(
            tool="edit",
            text="原文不匹配，编辑已拒绝",
            ok=False,
            repair_hint="文件第 2 行附近内容为：hello",
        )
    )
    assert "修复建议：文件第 2 行附近内容为：hello" in line


def test_compact_summarize_keeps_recent_six() -> None:
    """X-A6：/compact 保留最近 6 条、摘要 ≤2000 字符、原始记录保留。"""
    messages = _messages(20)
    summary, kept_ids = summarize(messages)
    assert len(kept_ids) == 6
    assert kept_ids == [f"message:{index}" for index in range(14, 20)]
    assert len(summary) <= 2000
    # 原始记录不删除
    assert len(messages) == 20


def test_compact_summarize_truncates_overlong() -> None:
    """X-A6：超长摘要截断带标记。"""
    messages = [{"role": "user", "content": "x" * 300, "source_id": "m1"}] * 10
    summary, _ = summarize(messages, max_summary_chars=100)
    assert len(summary) <= 105
    assert "截断" in summary


def test_parse_compact_strict_schema() -> None:
    """X-A6：CompactProtocol 严格校验（缺字段/多字段/版本拒绝）。"""
    raw = (
        '{"protocol": "compact", "version": "compact.v1", '
        '"summary": "摘要", "kept_ids": ["m1"], "token_count": 10}'
    )
    result = parse_compact(raw)
    assert result["version"] == COMPACT_VERSION
    assert result["fields"]["summary"] == "摘要"
    with pytest.raises(AppError):
        parse_compact('{"protocol": "compact", "version": "compact.v1", "summary": "摘要"}')
    with pytest.raises(AppError):
        parse_compact(raw.replace('"version": "compact.v1"', '"version": "compact.v0"'))


def test_project_meter_matches_context_meter() -> None:
    """X-A7：ContextMeter 投影字段与 context_meter 一致。"""
    meter = project_meter(
        {"token_used": 3000, "token_limit": 8192, "window_ratio": 0.37, "compacted": True}
    )
    assert meter is not None
    assert meter["token_used"] == 3000
    assert meter["token_limit"] == 8192
    assert meter["total_tokens"] == 3000
    assert meter["max_tokens"] == 8192
    assert meter["window_ratio"] == 0.37
    assert meter["compacted"] is True
    assert project_meter(None) is None
    assert project_meter({}) is None


def test_compute_meter_from_window_messages() -> None:
    """X-A7：服务端按窗口消息计算 token / 条数 / 余量，不依赖前端估算。"""
    messages = [
        {"role": "user", "content": "你好，请评测这两个模型", "source_id": "m1"},
        {"role": "assistant", "content": "请先确认数据集与协议档", "source_id": "m2"},
    ]
    meter = compute_meter(messages, max_tokens=200_000, skills_text="基准评测：执行大模型基准评测")
    assert meter["messages"] == 2
    assert meter["window"] == 20
    assert meter["headroom"] == 18
    assert meter["skills"] == 1
    assert meter["summary"] == 0
    assert meter["compacted"] is False
    assert meter["max_tokens"] == 200_000
    assert meter["messages_tokens"] == estimate_tokens(
        "你好，请评测这两个模型\n请先确认数据集与协议档"
    )
    assert meter["skills_tokens"] > 0
    assert meter["total_tokens"] == meter["messages_tokens"] + meter["skills_tokens"]
    assert meter["free_tokens"] == 200_000 - meter["total_tokens"]
    assert 0 <= meter["used_percent"] <= 100


def test_compute_meter_marks_compacted_summary() -> None:
    """已压缩会话：summary/compacted 置位，摘要计入 token。"""
    meter = compute_meter(
        [{"role": "user", "content": "继续", "source_id": "m9"}],
        compact_summary="此前已完成基准评测规划",
        max_tokens=1000,
    )
    assert meter["compacted"] is True
    assert meter["summary"] == 1
    assert meter["total_tokens"] > meter["messages_tokens"]
