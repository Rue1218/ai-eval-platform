"""回归测试：工具错误必须携带模型可见的修复建议（repair_hint）。

背景（生产事故）：execute_raw 的 AppError 分支只从 ``exc.fields.repair_hint``
提取修复建议；write 覆盖拒绝等错误只带 message（无 fields），模型只见
"操作失败（VALIDATION）"模糊文案，盲目重试直至 BUDGET_EXCEEDED。修复后
hint 回退 ``exc.message``，模型可直接改用 edit。
"""

import os
import tempfile

import pytest

from app.harness.contracts import ToolCall
from app.harness.execution.dispatch import execute_raw
from app.harness.execution.registry import build_default_registry


@pytest.fixture()
def registry():
    return build_default_registry()


@pytest.fixture()
def sandbox_dir() -> str:
    root = tempfile.mkdtemp(prefix="hint-test-")
    with open(os.path.join(root, "x.txt"), "w", encoding="utf-8") as handle:
        handle.write("old-content\n")
    return root


def _call(registry, name: str, arguments: dict) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, call_id=f"c-{name}")


def test_write_overwrite_error_carries_message_hint(registry, sandbox_dir) -> None:
    """write 覆盖已存在文件：repair_hint 必须包含具体原因（无 fields 时回退 message）。"""
    definition = registry.get("write")
    result = execute_raw(
        _call(registry, "write", {"path": "x.txt", "content": "new"}),
        timeout_s=10.0,
        permission="sandbox.write",
        sandbox_dir=sandbox_dir,
        handler=definition.handler,
        recovery_policy=definition.recovery_policy,
    )
    assert result.ok is False
    hint = (result.error or {}).get("repair_hint") or ""
    assert "文件已存在" in hint, f"write 覆盖错误缺少原因提示: {hint!r}"


def test_read_missing_error_carries_message_hint(registry, sandbox_dir) -> None:
    """read 不存在文件：repair_hint 必须包含"文件不存在"。"""
    definition = registry.get("read")
    result = execute_raw(
        _call(registry, "read", {"path": "nope.txt"}),
        timeout_s=10.0,
        permission="sandbox.read",
        sandbox_dir=sandbox_dir,
        handler=definition.handler,
        recovery_policy=definition.recovery_policy,
    )
    assert result.ok is False
    hint = (result.error or {}).get("repair_hint") or ""
    assert "文件不存在" in hint, f"read 错误缺少原因提示: {hint!r}"


def test_fields_repair_hint_takes_priority(registry, sandbox_dir) -> None:
    """显式 fields.repair_hint（如 edit 的邻近行建议）优先于 message。"""
    definition = registry.get("edit")
    result = execute_raw(
        _call(registry, "edit", {"path": "x.txt", "old": "不存在的原文", "new": "y"}),
        timeout_s=10.0,
        permission="sandbox.write",
        sandbox_dir=sandbox_dir,
        handler=definition.handler,
        recovery_policy=definition.recovery_policy,
    )
    assert result.ok is False
    hint = (result.error or {}).get("repair_hint") or ""
    # fields.repair_hint 优先：edit 的邻近行建议（含行号），而非 message 原文
    assert hint, "edit 不匹配必须携带邻近行修复建议"
    assert "原文不匹配" not in hint, "hint 应为邻近行建议而非 message 原文"
    assert "行" in hint, "邻近行建议应包含行号信息"
