"""用例生成 Skill 纯函数单测（M2 W8 / PRD 5.4.1）。

正本位于 worker 包（纯函数零依赖），按文件路径加载，CI 覆盖 worker
生成口径；覆盖 prompt 组装、容错解析、配比校正与自检红字规则。
"""

import importlib.util
from pathlib import Path

# worker 侧用例生成纯函数路径：backend/worker/app/casegen.py
_CASEGEN_PATH = Path(__file__).resolve().parents[2] / "worker" / "app" / "casegen.py"
_spec = importlib.util.spec_from_file_location("worker_casegen", _CASEGEN_PATH)
casegen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(casegen)


def test_build_prompts_contains_ratio_and_source():
    # prompt 必须包含六策略配比说明与来源文档
    system, user = casegen.build_prompts("登录模块需求", 45)
    assert "正向" in system and "反向" in system and "边界" in system
    assert "等价类" in system and "状态迁移" in system and "场景" in system
    assert "只输出一个 JSON 数组" in system
    assert "45" in user and "登录模块需求" in user
    for key, weight in casegen.STRATEGY_WEIGHTS.items():
        assert f"{casegen.STRATEGY_NAMES[key]} {weight}%" in user


def test_parse_cases_tolerates_fences_and_prose():
    # 允许代码围栏与首尾解释文字
    raw = '好的，以下是用例：\n```json\n[{"name": "登录成功", "strategy": "正向"}]\n```\n以上共 1 条。'
    cases = casegen.parse_cases(raw)
    assert len(cases) == 1 and cases[0]["name"] == "登录成功"


def test_parse_cases_rejects_invalid_payload():
    import pytest

    with pytest.raises(ValueError):
        casegen.parse_cases("完全不是 JSON 的输出")
    with pytest.raises(ValueError):
        casegen.parse_cases('{"name": "对象而非数组"}')
    with pytest.raises(ValueError):
        casegen.parse_cases("[{\"strategy\": \"正向\"}]")  # 无 name 的条目被过滤后为空


def test_rebalance_trims_overweight_strategy():
    # 正向超配比被截断；总条数不超上限
    cases = [{"name": f"用例{i}", "strategy": "正向"} for i in range(40)]
    cases += [{"name": f"反用例{i}", "strategy": "反向"} for i in range(5)]
    result = casegen.rebalance_by_strategy(cases, 45)
    positives = [c for c in result if c["strategy"] == "正向"]
    negatives = [c for c in result if c["strategy"] == "反向"]
    # 45 条配额：正向 18（40%）、反向 11（25%）；不足的 5 条反向全保留
    assert len(positives) == 18
    assert len(negatives) == 5
    assert len(result) <= 45


def test_selfcheck_flags_missing_core_positive_and_negative():
    # 无正向用例 + 无反向用例：两条红字
    cases = [{"name": "边界值", "strategy": "边界"}]
    checks = casegen.selfcheck(cases)
    codes = {check["code"] for check in checks}
    assert codes == {"no_core_positive", "missing_constraint_negative"}
    assert all(check["level"] == "error" for check in checks)


def test_selfcheck_flags_positive_without_core():
    # 有正向但无 P0/核心：仍红字 no_core_positive
    cases = [
        {"name": "普通正向", "strategy": "正向", "priority": "P2"},
        {"name": "反向用例", "strategy": "反向"},
    ]
    codes = {check["code"] for check in casegen.selfcheck(cases)}
    assert codes == {"no_core_positive"}


def test_selfcheck_passes_with_core_positive_and_negative():
    # P0 正向 + 反向齐全：无红字
    cases = [
        {"name": "核心登录", "strategy": "正向", "priority": "P0"},
        {"name": "密码错误", "strategy": "反向"},
    ]
    assert casegen.selfcheck(cases) == []


def test_scale_contract_constants():
    # 规模口径：中等目标 45、硬上限 80（PRD 5.4.1）
    assert casegen.TARGET_COUNT == 45
    assert casegen.MAX_COUNT == 80
