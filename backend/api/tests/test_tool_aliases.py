"""原生工具字段别名、replace_all 与禁止关沙箱/后台执行。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.errors import AppError, ErrorCode
from app.harness.execution.aliases import (
    bash_timeout_seconds,
    enforce_tool_argument_policy,
    normalize_tool_arguments,
)
from app.harness.execution.dispatch import (
    assert_fetch_domains,
    build_task_plan,
    edit_file_safe,
)
from app.harness.execution.registry import build_default_registry, validate_tool_arguments


def test_normalize_maps_legacy_file_and_edit_keys() -> None:
    """旧 path/old/new 归一为 file_path/old_string/new_string 后删除旧键。"""
    read_args = normalize_tool_arguments("read", {"path": "a.txt", "next_offset": 3})
    assert read_args == {"file_path": "a.txt", "offset": 3}
    edit_args = normalize_tool_arguments(
        "edit", {"path": "a.txt", "old": "x", "new": "y", "replace_all": True}
    )
    assert edit_args["file_path"] == "a.txt"
    assert edit_args["old_string"] == "x"
    assert edit_args["new_string"] == "y"
    assert "path" not in edit_args
    assert "old" not in edit_args


def test_normalize_does_not_override_canonical_file_path() -> None:
    """模型同时给新旧名时保留 canonical 值。"""
    args = normalize_tool_arguments("read", {"path": "old.txt", "file_path": "new.txt"})
    assert args == {"file_path": "new.txt"}


def test_task_aliases_fill_description_and_prompt() -> None:
    """旧 goal 映射为 prompt，并截短补齐 description。"""
    args = normalize_tool_arguments("task", {"goal": "审查整条工具链路并输出风险"})
    assert args["prompt"] == "审查整条工具链路并输出风险"
    assert args["description"].startswith("审查整条工具链路")
    assert "goal" not in args


def test_schema_accepts_canonical_names_after_normalize() -> None:
    """归一化后的参数必须通过 additionalProperties=false 的新 Schema。"""
    registry = build_default_registry()
    for name, raw in (
        ("read", {"path": "a.txt"}),
        ("write", {"path": "a.txt", "content": "hi"}),
        ("edit", {"path": "a.txt", "old": "a", "new": "b"}),
        ("web_search", {"query": "评测", "limit": 3}),
        ("task", {"goal": "拆解计划", "steps": [{"title": "第一步", "status": "pending"}]}),
    ):
        normalized = normalize_tool_arguments(name, raw)
        assert validate_tool_arguments(registry.get(name).parameters_schema, normalized) is None


def test_bash_policy_rejects_sandbox_escape_and_background() -> None:
    """关沙箱与后台执行必须 VALIDATION，不得静默忽略。"""
    with pytest.raises(AppError) as escaped:
        enforce_tool_argument_policy("bash", {"command": "ls", "dangerouslyDisableSandbox": True})
    assert escaped.value.code == ErrorCode.VALIDATION
    assert "沙箱" in escaped.value.message
    with pytest.raises(AppError) as background:
        enforce_tool_argument_policy("bash", {"command": "ls", "run_in_background": True})
    assert background.value.code == ErrorCode.VALIDATION


def test_bash_timeout_is_capped_at_sandbox_wall() -> None:
    """timeout 毫秒换算后不得超过现有 15s 墙钟。"""
    assert bash_timeout_seconds({}) == 15.0
    assert bash_timeout_seconds({"timeout": 2000}) == 2.0
    assert bash_timeout_seconds({"timeout": 120000}) == 15.0


def test_web_engine_rejects_unimplemented_provider() -> None:
    """未实现的 engine 不得假装已切换搜索商。"""
    with pytest.raises(AppError) as error:
        enforce_tool_argument_policy("web_search", {"query": "x", "engine": "exa"})
    assert error.value.code == ErrorCode.VALIDATION


def test_fetch_domain_lists_are_enforced() -> None:
    """web_fetch 按 host 强制白/黑名单。"""
    assert_fetch_domains("https://example.com/a", allowed=["example.com"], blocked=[])
    with pytest.raises(AppError):
        assert_fetch_domains("https://evil.test/a", allowed=["example.com"], blocked=[])
    with pytest.raises(AppError):
        assert_fetch_domains("https://example.com/a", allowed=[], blocked=["example.com"])


def test_edit_replace_all_and_multiple_matches(tmp_path: Path) -> None:
    """默认必须唯一匹配；replace_all 才替换全部。"""
    root = tmp_path / "ws"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("foo foo", encoding="utf-8")
    with pytest.raises(AppError) as unique:
        edit_file_safe("note.txt", "foo", "bar", str(root), replace_all=False)
    assert unique.value.fields
    assert unique.value.fields["error"] == "MultipleMatches"
    result = edit_file_safe("note.txt", "foo", "bar", str(root), replace_all=True)
    assert result.replacements == 2
    assert os.path.exists(target)
    assert target.read_text(encoding="utf-8") == "bar bar"
    assert result.diff.startswith("@@")


def test_task_plan_uses_full_step_list_and_rejects_duplicate_steps() -> None:
    """task 每次都以完整步骤清单为准，重复条目必须在执行前被拒绝。"""
    result = build_task_plan({
        "description": "检查工具链路",
        "steps": [
            {"title": "读取注册表", "status": "completed"},
            {"title": "验证前端投影", "status": "in_progress"},
        ],
    })
    assert result.goal == "检查工具链路"
    assert result.description == "检查工具链路"
    assert result.steps[1]["status"] == "in_progress"
    data = result.to_tool_data()
    assert data["display"]["status"] == "success"
    assert data["display"]["result"]

    with pytest.raises(AppError, match="重复"):
        build_task_plan({
            "description": "检查工具链路",
            "steps": [
                {"title": "读取注册表", "status": "pending"},
                {"title": "读取注册表", "status": "in_progress"},
            ],
        })
