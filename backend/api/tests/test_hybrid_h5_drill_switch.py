"""H5 收尾演练开关测试（agent_drill_sandbox_enabled，默认 False fail-closed）。

覆盖三层：
1. 默认（开关 False）：任何 capabilities 请求都不得 discover 到
   ``worker.sandbox``（含 run_script 请求零命中回落 general）；
2. 开关 True（仅演练环境）：请求含 ``run_script``/``verify_output`` 时选中
   ``worker.sandbox``（allowed_tools 含 bash，供制造危险 bash 审批卡）；
   混合能力（read_workspace + run_script）保守回落 general（双闸）；
3. intent 词表：带 code 触发词的意图产生 run_script 能力请求。
"""

import pytest

from app.agent.taor_nodes import _capabilities_from_intent
from app.config import settings
from app.harness.orchestration.agents import AgentRegistry, build_default_agent_registry


def _ids(reg: AgentRegistry) -> set[str]:
    return {def_.agent_id for def_ in reg.iter_defs()}


def _default_registry(drill: bool, monkeypatch: pytest.MonkeyPatch) -> AgentRegistry:
    """按演练开关构建完整默认注册表（4 Worker；monkeypatch 还原开关）。"""
    monkeypatch.setattr(settings, "agent_drill_sandbox_enabled", drill)
    return build_default_agent_registry()


def test_default_registry_contains_four_workers() -> None:
    reg = build_default_agent_registry()
    assert _ids(reg) == {"worker.general", "worker.diagnose", "worker.dataset", "worker.sandbox"}


def test_config_default_keeps_sandbox_excluded() -> None:
    assert settings.agent_drill_sandbox_enabled is False  # 默认 fail-closed


def test_drill_off_run_script_request_falls_back_to_general(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开关默认关：即使请求 run_script，也绝不含 sandbox（双闸第一闸）。"""
    reg = _default_registry(False, monkeypatch)
    picked = reg.discover(capabilities=frozenset({"run_script", "verify_output"}))
    assert picked.agent_id == "worker.general"
    assert "bash" not in picked.allowed_tools


def test_drill_on_selects_sandbox_with_bash_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开（演练专用）：run_script 能力请求选中 sandbox，视野含 bash。"""
    reg = _default_registry(True, monkeypatch)
    picked = reg.discover(capabilities=frozenset({"run_script", "verify_output"}))
    assert picked.agent_id == "worker.sandbox"
    assert picked.allowed_tools == ("read", "bash")
    assert picked.max_permission == "code"


def test_drill_on_partial_run_script_request_still_selects_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_script ⊆ sandbox 声明即命中（演练触发不必全能力）。"""
    reg = _default_registry(True, monkeypatch)
    picked = reg.discover(capabilities=frozenset({"run_script"}))
    assert picked.agent_id == "worker.sandbox"


def test_drill_on_mixed_capabilities_falls_back_to_general(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """混合能力（read_workspace + run_script）无单 Worker 全含 → 保守回落 general。"""
    reg = _default_registry(True, monkeypatch)
    picked = reg.discover(capabilities=frozenset({"read_workspace", "run_script"}))
    assert picked.agent_id == "worker.general"
    assert "bash" not in picked.allowed_tools


@pytest.mark.parametrize(
    "intent",
    ["帮我运行脚本看看输出", "执行命令清理临时目录", "跑脚本验证一下", "运行代码做个冒烟"],
)
def test_intent_keywords_produce_run_script_capabilities(intent: str) -> None:
    caps = _capabilities_from_intent(intent)
    assert "run_script" in caps


def test_plain_question_never_requests_run_script() -> None:
    caps = _capabilities_from_intent("排查一下测试环境异常")
    assert "run_script" not in caps
    assert caps  # 仍走 diagnose 能力
