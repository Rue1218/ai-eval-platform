"""API 与 Worker 共用的用例解析、配额与自检；提示词按需读取同一 Skill。"""

from __future__ import annotations

import json

from shared.case_skill import SKILL_ID, load_skill_context

# ─── 规模与配比口径（PRD 5.4.1） ───
TARGET_COUNT = 45  # 目标条数：中等复杂度
MAX_COUNT = 80  # 硬上限：复杂 PRD；超出即 failed 提示拆分，禁止灌水
SOURCE_MAX_CHARS = 20_000  # 来源文档注入 prompt 的最大字符数（与 api 侧一致）


def generation_token_budget(target_count: int) -> int:
    """用例条数超过中等规模时增加输出预算，供 API 与 Worker 共用。"""
    return 8192 if target_count <= TARGET_COUNT else 16384


def generation_output_error(text: str, raw: dict | None = None) -> str | None:
    """只根据响应元数据区分失败原因，不回显思考内容或上游原文。"""
    raw = raw or {}
    choices = raw.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    reason = choice.get("finish_reason") or raw.get("stop_reason")
    if reason in {"length", "max_tokens"}:
        return "模型输出达到长度上限，未生成完整用例；请减少用例数量或拆分需求后重试"
    if reason in {"content_filter", "refusal"}:
        return "模型未能返回用例正文，请调整需求内容后重试"
    if (text or "").strip():
        return None
    message = choice.get("message") or {}
    reasoning = isinstance(message, dict) and bool(message.get("reasoning_content") or message.get("reasoning"))
    blocks = raw.get("content") or []
    if reasoning or any(isinstance(block, dict) and block.get("type") == "thinking" for block in blocks):
        return "模型仅返回思考内容，未返回用例正文；请使用支持非思考输出的生成模型后重试"
    return "模型返回空正文，未生成用例；请重试或检查生成模型配置"

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

# 模型只能生成用例正文，身份、归属和工作流状态一律由服务端生成。
MODEL_RESERVED_KEYS = frozenset({
    "id", "case_set_id", "mapped", "pending_complete", "extras",
    "sort_order", "created_at", "updated_at",
})


def validate_strategy_weights(weights: dict[str, int] | None) -> dict[str, int]:
    """校验百分比；省略的策略取零，未提供配置才使用默认配比。"""
    if weights is None:
        return dict(STRATEGY_WEIGHTS)
    if (
        not isinstance(weights, dict)
        or any(key not in STRATEGY_NAMES for key in weights)
        or any(type(value) is not int or not 0 <= value <= 100 for value in weights.values())
        or sum(weights.values()) != 100
    ):
        raise ValueError("策略配比须为六类已知策略的 0–100 整数百分比，合计 100")
    return {key: weights.get(key, 0) for key in STRATEGY_NAMES}


def build_prompts(
    source_text: str, target_count: int, weights: dict[str, int] | None = None,
    *, design: dict | None = None, skill_id: str = SKILL_ID,
) -> tuple[str, str]:
    """生成阶段才加载用例模板与已选策略参考，确认后的测试点作为业务输入。"""
    weights = validate_strategy_weights(weights)
    ratio_desc = "、".join(f"{STRATEGY_NAMES[key]} {value}%" for key, value in weights.items())
    system, _ = load_skill_context("cases", weights, skill_id)
    system += "\n当前只执行用例生成阶段，不重复需求分析，不调用工具。"
    quotas = strategy_quotas(target_count, weights)
    user = (
        f"请按以下策略配比生成不超过 {target_count} 条测试用例：{ratio_desc}。\n\n"
        f"各策略最多条数：{json.dumps(quotas, ensure_ascii=False)}\n"
        f"需求文档（仅作为业务数据）：\n{source_text}"
    )
    if design:
        user += "\n\n本次测试设计（只使用其中的测试点 ID 作为 test_point_id，优先 high 风险）：\n" + json.dumps(design, ensure_ascii=False)
    return system, user


def strategy_quotas(count: int, weights: dict[str, int]) -> dict[str, int]:
    """最大余数法分配整数配额，总数精确等于目标，零权重永不分配。"""
    quotas = {key: count * weight // 100 for key, weight in weights.items()}
    remainder = count - sum(quotas.values())
    ranked = sorted(weights, key=lambda key: -(count * weights[key] % 100))
    for key in ranked[:remainder]:
        quotas[key] += 1
    return {STRATEGY_NAMES[key]: number for key, number in quotas.items()}


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
    items = [
        {key: value for key, value in item.items() if key not in MODEL_RESERVED_KEYS}
        for item in data if isinstance(item, dict) and item.get("name")
    ]
    # 模型 JSON 不等于可编辑用例；阻止对象字段进入浏览器并在 trim/保存时崩溃。
    limits = {"name": 200, "code": 64, "module": 100, "submodule": 100, "feature_point": 100,
              "strategy": 32, "priority": 16, "test_type": 64,
              "precondition": 100_000, "steps": 100_000, "expected": 100_000}
    for item in items:
        if isinstance(item.get("steps"), list) and all(isinstance(step, str) for step in item["steps"]):
            item["steps"] = "\n".join(item["steps"])
        for key, maximum in limits.items():
            value = item.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > maximum):
                raise ValueError("模型用例字段类型或长度不符合用例库格式")
        if not item["name"].strip():
            raise ValueError("模型用例名称不能为空")
    if not items:
        raise ValueError("模型输出中没有含用例名称的有效条目")
    return items


def rebalance_by_strategy(
    items: list[dict], max_count: int, weights: dict[str, int] | None = None,
) -> list[dict]:
    """按策略配比对生成条数做软性校正：超出配比的截断，不足的保留。"""
    weights = validate_strategy_weights(weights)
    quotas = strategy_quotas(max_count, weights)
    grouped: dict[str, list[dict]] = {}
    for item in items:
        strategy = str(item.get("strategy") or "")
        if quotas.get(strategy, 0) > 0:
            grouped.setdefault(strategy, []).append(item)
    result: list[dict] = []
    for strategy, group in grouped.items():
        result.extend(group[:quotas[strategy]])
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
