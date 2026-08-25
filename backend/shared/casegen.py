"""用例生成纯函数集（PRD 5.4.1 / 后端计划 M2 W8）。

prompt 组装、模型输出解析、策略配比校正与自检红字全部为纯函数零依赖：
api 侧测试按文件路径直接加载（见 ``backend/api/tests/test_casegen.py``），
worker 执行器运行时同源引用，保证两端生成口径一致。修改时必须保持零
import 约束，prompt 文案与 ``api/app/routers/cases.py`` 的 ai-generate 对齐。
"""

from __future__ import annotations

import json

# ─── 规模与配比口径（PRD 5.4.1） ───
TARGET_COUNT = 45  # 目标条数：中等复杂度
MAX_COUNT = 80  # 硬上限：复杂 PRD；超出即 failed 提示拆分，禁止灌水
SOURCE_MAX_CHARS = 20_000  # 来源文档注入 prompt 的最大字符数（与 api 侧一致）

# 六大策略默认配比（正向40/反向25/边界15/等价类10/状态迁移5/场景5，与 api 侧一致）
STRATEGY_WEIGHTS = {
    "positive": 40,
    "negative": 25,
    "boundary": 15,
    "equivalence": 10,
    "state": 5,
    "scenario": 5,
}
STRATEGY_NAMES = {
    "positive": "正向",
    "negative": "反向",
    "boundary": "边界",
    "equivalence": "等价类",
    "state": "状态迁移",
    "scenario": "场景",
}

# 优先级六档（PRD 用例模板）：核心/非核心/边界问题/异常/中断/遍历
PRIORITY_VALUES = ("HX", "FHX", "BJ", "YC", "ZD", "BL")
PRIORITY_LABELS = {
    "HX": "核心",
    "FHX": "非核心",
    "BJ": "边界问题",
    "YC": "异常",
    "ZD": "中断",
    "BL": "遍历",
}


def build_prompts(
    source_text: str, target_count: int, weights: dict[str, int] | None = None
) -> tuple[str, str]:
    """组装六策略用例生成的中文 system / user prompt（口径对齐 api ai-generate）。"""
    weights = weights or STRATEGY_WEIGHTS
    ratio_desc = "、".join(f"{STRATEGY_NAMES[key]} {value}%" for key, value in weights.items())
    priority_desc = "、".join(f"{value}（{PRIORITY_LABELS[value]}）" for value in PRIORITY_VALUES)
    system = (
        "你是资深测试设计专家，负责根据需求文档设计软件测试用例。"
        "每条用例必须包含 strategy（策略，取值限于 正向/反向/边界/等价类/状态迁移/场景）、"
        f"priority（优先级，取值限于 {priority_desc}）、"
        "module（模块）、submodule（子模块）、feature_point（功能点）、"
        "name（测试点/用例名称）、expected（预期结果）、precondition（前置条件）、"
        "test_type（测试类型，如 核心业务/异常处理/兼容性），可选 steps（操作步骤）。"
        "只输出一个 JSON 数组，不要输出任何解释文字或 markdown 代码围栏。"
    )
    user = (
        f"请按以下策略配比生成不超过 {target_count} 条测试用例：{ratio_desc}。\n\n"
        f"需求文档：\n{source_text}"
    )
    return system, user


def parse_cases(text: str) -> list[dict]:
    """从容错模型输出提取用例 JSON 数组（允许代码围栏与首尾解释文字）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("模型未返回可解析的用例 JSON 数组")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("模型返回的不是 JSON 数组")
    items = [item for item in data if isinstance(item, dict) and item.get("name")]
    if not items:
        raise ValueError("模型输出中没有含用例名称的有效条目")
    return items


def rebalance_by_strategy(items: list[dict], max_count: int) -> list[dict]:
    """按策略配比对生成条数做软性校正：超出配比的截断，不足的保留。"""
    total_weight = sum(STRATEGY_WEIGHTS.values())
    quotas = {
        STRATEGY_NAMES[key]: (max(1, round(max_count * w / total_weight)) if w > 0 else 0)
        for key, w in STRATEGY_WEIGHTS.items()
    }
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(str(item.get("strategy") or ""), []).append(item)
    result: list[dict] = []
    for strategy, group in grouped.items():
        quota = quotas.get(strategy)
        result.extend(group if quota is None else group[:quota])
    return result[:max_count]


def selfcheck(cases: list[dict]) -> list[dict]:
    """自检红字（PRD 5.4.1 P0）：无核心正向、缺约束反向 → 确认页红字检查项。"""
    checks: list[dict] = []
    positives = [case for case in cases if case.get("strategy") == "正向"]
    core_positives = [
        case
        for case in positives
        if case.get("priority") == "HX" or "核心" in str(case.get("test_type") or "")
    ]
    if not positives:
        checks.append({"level": "error", "code": "no_core_positive", "message": "自检未通过：未生成任何正向策略用例"})
    elif not core_positives:
        checks.append({"level": "error", "code": "no_core_positive", "message": "自检未通过：正向用例中没有 HX 核心用例"})
    negatives = [case for case in cases if case.get("strategy") == "反向"]
    if not negatives:
        checks.append({"level": "error", "code": "missing_constraint_negative", "message": "自检未通过：缺少反向（约束/异常）策略用例"})
    return checks
