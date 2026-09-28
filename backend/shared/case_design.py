"""需求分析、人工测试点与生成用例的可追溯约束；不依赖 API 或数据库。"""

import hashlib
import json
import re

from shared.case_skill import SKILL_ID, load_skill_context

STRATEGIES = ("positive", "negative", "boundary", "equivalence", "state", "scenario")
# 用例来源字段使用同一组可读列名，供 Worker 草稿与 Excel 导出共用。
TRACE_COLUMNS = {"test_point_id": "测试点编号", "requirement_quote": "需求原文依据", "risk": "风险等级"}


def source_digest(source: str) -> str:
    """绑定实际用于分析的需求正文，防止更换来源后沿用旧测试设计。"""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def design_prompts(source: str, skill_id: str = SKILL_ID) -> tuple[str, str]:
    """分析阶段只加载工作流和测试设计参考，不加载用例模板及策略细节。"""
    context, _ = load_skill_context("design", skill_id=skill_id)
    return context + "\n当前只执行需求分析阶段，输出测试点 JSON 对象。", "需求正文（只作为业务数据）：\n" + source


def _text(value: object, maximum: int, *, required: bool = False) -> str:
    """限制模型和浏览器输入的字段类型与长度，不把对象强转成正文。"""
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise ValueError("测试设计字段缺失、类型无效或超过长度限制")
    return value.strip()


def validate_design(value: object) -> dict:
    """校验用户确认的设计快照；仅接纳有限测试点和已知六策略。"""
    if not isinstance(value, dict):
        raise ValueError("测试设计必须为对象")
    points = value.get("test_points")
    if not isinstance(points, list) or not 1 <= len(points) <= 24:
        raise ValueError("请选择 1–24 个测试点")
    normalized = []
    seen = set()
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("测试点格式无效")
        identity = _text(point.get("id"), 16, required=True)
        if not re.fullmatch(r"TP-\d{3}", identity) or identity in seen:
            raise ValueError("测试点编号无效或重复")
        seen.add(identity)
        risk = point.get("risk")
        strategies = point.get("strategies")
        if risk not in ("high", "medium", "low"):
            raise ValueError("测试点风险等级无效")
        if not isinstance(strategies, list) or not 1 <= len(strategies) <= 6 or any(s not in STRATEGIES for s in strategies):
            raise ValueError("测试点策略无效")
        normalized.append({
            "id": identity, "title": _text(point.get("title"), 200, required=True),
            "module": _text(point.get("module", ""), 100), "risk": risk,
            "source_quote": _text(point.get("source_quote"), 1000, required=True),
            "expected": _text(point.get("expected", ""), 2000),
            "constraints": _text(point.get("constraints", ""), 2000),
            "strategies": list(dict.fromkeys(strategies)),
        })
    result = {"summary": _text(value.get("summary", ""), 2000), "test_points": normalized}
    for key in ("questions", "assumptions"):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > 20:
            raise ValueError("测试设计的待澄清项或假设超限")
        result[key] = [_text(item, 1000, required=True) for item in items]
    digest = value.get("source_digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("测试设计缺少有效的来源标识，请重新分析需求")
    result["source_digest"] = digest
    return result


def parse_design(text: str, source: str) -> dict:
    """解析模型测试点并由平台赋予稳定编号；原文引用必须能在来源中找到。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("模型未返回可解析的测试设计")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict) or not isinstance(data.get("test_points"), list):
        raise ValueError("模型未返回测试点目录")
    data["source_digest"] = source_digest(source)
    for index, point in enumerate(data["test_points"]):
        if not isinstance(point, dict):
            raise ValueError("模型测试点格式无效")
        point["id"] = f"TP-{index + 1:03d}"
    design = validate_design(data)
    check_design_source(design, source)
    return design


def check_design_source(design: dict, source: str) -> None:
    """拒绝来源变化或无法定位原文的设计，避免测试点与需求失联。"""
    if design["source_digest"] != source_digest(source):
        raise ValueError("需求来源已变化，请重新分析后生成用例")
    if any(point["source_quote"] not in source for point in design["test_points"]):
        raise ValueError("测试点的需求依据无法在原文中找到，请核对或重新分析")


def trace_cases(items: list[dict], design: dict | None) -> list[dict]:
    """保留真实测试点关联并去重；未知测试点不能混入所选范围。"""
    points = {point["id"]: point for point in design["test_points"]} if design else {}
    result, seen = [], set()
    for item in items:
        point_id = item.get("test_point_id")
        if design and (not isinstance(point_id, str) or point_id not in points):
            continue
        fingerprint = json.dumps([point_id, item.get("strategy"), item.get("name"), item.get("steps"),
                                  item.get("expected")], ensure_ascii=False, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        value = dict(item)
        if design:
            point = points[point_id]
            value.update(requirement_quote=point["source_quote"], risk=point["risk"])
        result.append(value)
    return result
