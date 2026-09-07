"""执行选择显式化单测（dsh 改进 #5：resolve 决策点三档 + 默认行为不变）。

覆盖：常规沙箱（bwrap）/ drill 演练放行 / 排除 fail-closed 三档判定；
bash 引擎 off 时 fail-closed；discover 默认路径 worker.sandbox 仍不可选中。
"""

from __future__ import annotations

from app.harness.orchestration.agents import build_default_agent_registry
from app.harness.security.exec_policy import (
    SANDBOX_WORKER_ID,
    ExecVerdict,
    resolve_bash_engine,
    resolve_worker_visible,
)


def _assert_verdict(verdict: ExecVerdict, allow: bool, mode: str) -> None:
    assert verdict.allow is allow
    assert verdict.mode == mode
    assert verdict.reason


def test_bash_engine_three_tiers() -> None:
    """bwrap 放行；off / 未知引擎 fail-closed（三档显式判定）。"""
    _assert_verdict(resolve_bash_engine("bwrap"), True, "bwrap")
    _assert_verdict(resolve_bash_engine("off"), False, "off")
    _assert_verdict(resolve_bash_engine(""), False, "off")
    _assert_verdict(resolve_bash_engine("docker"), False, "off")
    # off 文案沿用历史用户提示（说明 bwrap 缺失属 fail-closed 原因，非伪装可用）
    assert "read/write/edit" in resolve_bash_engine("off").reason


def test_worker_visibility_three_tiers() -> None:
    """常规 Worker 恒可见；worker.sandbox 默认排除（fail-closed）、drill 放行。"""
    _assert_verdict(resolve_worker_visible("worker.general", drill_enabled=False), True, "normal")
    _assert_verdict(resolve_worker_visible("worker.sandbox", drill_enabled=False), False, "fail-closed")
    _assert_verdict(resolve_worker_visible("worker.sandbox", drill_enabled=True), True, "drill")
    assert "复位" in resolve_worker_visible("worker.sandbox", drill_enabled=True).reason


def test_discover_default_still_excludes_sandbox() -> None:
    """默认（drill=false）discover 永不可选中 worker.sandbox（全量回归锚点）。"""
    registry = build_default_agent_registry()  # settings.agent_drill_sandbox_enabled=False
    picked = registry.discover(capabilities=frozenset({"run_script", "verify_output"}))
    assert picked.agent_id != SANDBOX_WORKER_ID
    # 常规 general 意图不受影响
    general = registry.discover(capabilities=frozenset({"general"}))
    assert general.agent_id == "worker.general"


def test_drill_enabled_discover_selects_sandbox() -> None:
    """演练开启时 discover 可按 code 能力选中 worker.sandbox（演练专用）。"""
    registry = build_default_agent_registry()
    # 绕过 settings：直接验证 Registry 构造参数语义（演练开关注入点）
    from app.harness.orchestration.agents import AgentRegistry

    registry = AgentRegistry(drill_sandbox_enabled=True)
    for def_ in build_default_agent_registry().iter_defs():
        registry.register(def_)
    picked = registry.discover(capabilities=frozenset({"run_script", "verify_output"}))
    assert picked.agent_id == SANDBOX_WORKER_ID
