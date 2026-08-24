"""M6 反馈层单测（F-A1/F-A2）；不依赖 DB（门禁上下文由调用方填）。"""

from app.errors import ErrorCode
from app.harness.contracts import ToolCall, ToolResult
from app.harness.feedback import (
    GateContext,
    check_gates,
    normalize,
    normalize_exception,
)
from app.harness.feedback.rules import BASH_BLOCK_PREFIXES


def _call(name: str, **arguments: object) -> ToolCall:
    """构造工具调用。"""
    return ToolCall(name=name, arguments=arguments)


def _ctx(**overrides: object) -> GateContext:
    """构造门禁上下文（默认全通过）。"""
    base: dict[str, object] = {
        "session_id": "s1",
        "user_id": "u1",
        "has_active_task": False,
        "owned_file_ids": frozenset({"file-1"}),
        "registered_names": frozenset({"read", "web_search", "task.create"}),
        "required_slots": {"task.create": ("kind", "dataset")},
    }
    base.update(overrides)
    return GateContext(**base)  # type: ignore[arg-type]


def test_normalize_ok_result() -> None:
    """F-A1：正常结果归一为 ok=True observation。"""
    observation = normalize(
        ToolResult(name="read", ok=True, data={"summary": "文件内容", "truncated": True}),
        None,
        tool="read",
    )
    assert observation.ok is True
    assert observation.text == "文件内容"
    assert observation.truncated is True
    assert observation.redacted is True


def test_normalize_exception_does_not_raise() -> None:
    """F-A1：异常不裸抛，归一为 ok=False observation。"""
    observation = normalize_exception(
        RuntimeError("secret traceback"), tool="web_search"
    )
    assert observation.ok is False
    assert "secret traceback" not in observation.text
    assert observation.text == "操作失败（INTERNAL）"


def test_normalize_app_error_uses_error_code() -> None:
    """异常带 ErrorCode 时文本只含错误码，不暴露原文。"""
    from app.errors import AppError

    observation = normalize(
        None,
        AppError(ErrorCode.UPSTREAM, "上游 502 内部细节"),
        tool="web_fetch",
    )
    assert observation.ok is False
    assert observation.text == "操作失败（UPSTREAM）"
    assert "502" not in observation.text


def test_gate_all_checks_pass() -> None:
    """F-A2：全部门禁通过。"""
    result = check_gates(_call("read", path="a.txt"), _ctx())
    assert result.passed is True


def test_gate_long_tool_rejected() -> None:
    """F-A2：长工具（benchmark.run）对话回合内拒绝。"""
    result = check_gates(_call("benchmark.run"), _ctx())
    assert result.passed is False
    assert result.failed_code == "VALIDATION"


def test_gate_unregistered_rejected() -> None:
    """F-A2：未注册工具拒绝（白名单）。"""
    result = check_gates(_call("evil_tool"), _ctx())
    assert result.passed is False
    assert result.failed_code == "VALIDATION"


def test_gate_bash_blocklist_rejected() -> None:
    """F-A2：bash 黑名单命令拒绝。"""
    for prefix in BASH_BLOCK_PREFIXES:
        result = check_gates(
            _call("bash", command=f"{prefix}target"), _ctx(registered_names=frozenset({"bash"}))
        )
        assert result.passed is False


def test_gate_unknown_kind_rejected() -> None:
    """F-A2：确认卡 kind 越界拒绝（一单一 kind）。"""
    result = check_gates(
        _call("task.create", kind="hack", dataset="d"), _ctx()
    )
    assert result.passed is False


def test_gate_required_slots_missing() -> None:
    """F-A2：必填槽位缺失拒绝。"""
    result = check_gates(_call("task.create", kind="benchmark"), _ctx())
    assert result.passed is False
    assert "dataset" in (result.failed_message or "")


def test_gate_file_not_owned_rejected() -> None:
    """F-A2：附件非归属用户拒绝（资产溯源）。"""
    result = check_gates(
        _call("read", path="a.txt", file_id="file-999"), _ctx()
    )
    assert result.passed is False
    assert "附件" in (result.failed_message or "")


def test_gate_active_task_blocks_confirm() -> None:
    """F-A2：会话存在活动任务时禁止再发确认卡（占槽，CONCURRENCY 语义）。"""
    result = check_gates(
        _call("task.create", kind="benchmark", dataset="d"), _ctx(has_active_task=True)
    )
    assert result.passed is False
    assert result.failed_code == "CONCURRENCY"
    # 非确认卡工具不受占槽限制
    assert check_gates(_call("read", path="a.txt"), _ctx(has_active_task=True)).passed


def test_gate_stress_requires_quality_derivation() -> None:
    """F-A2：压测须由质量任务成功派生（先评后压）。"""
    result = check_gates(
        _call("task.create", kind="stress", dataset="d"), _ctx()
    )
    assert result.passed is False
    assert "压测" in (result.failed_message or "")
