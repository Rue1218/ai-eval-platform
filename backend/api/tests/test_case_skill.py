"""用例 Skill 渐进披露、来源绑定与生成范围回归。"""

import hashlib
import json
from pathlib import Path

import pytest
from shared import case_skill
from shared.case_design import check_design_source, parse_design, trace_cases, validate_design
from shared.casegen import STRATEGY_WEIGHTS, strategy_quotas


def design_output(source="登录需求"):
    """模拟供应商测试设计，不信任供应商自己提供的编号与来源哈希。"""
    return json.dumps({"summary": "验证登录", "questions": ["失败提示是什么？"], "assumptions": [],
                       "test_points": [{"id": "forged", "title": "登录", "module": "账户",
                                        "source_quote": source, "risk": "high", "expected": "",
                                        "strategies": ["positive", "negative"]}]}, ensure_ascii=False)


def test_catalog_does_not_read_body_or_references(monkeypatch):
    """目录只读取入口头部；正文读取器被禁止时仍可发现技能。"""
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("目录不能加载正文或参考资源"))
    catalog = case_skill.read_skill_section("catalog")
    assert catalog["skills"][0]["id"] == "functional-test-design"
    assert "content" not in catalog["skills"][0]


@pytest.mark.parametrize("stage,weights,sections", [
    ("design", {"boundary": 100}, ["workflow", "design"]),
    ("cases", {"positive": 100}, ["workflow", "cases"]),
    ("cases", {"boundary": 100}, ["workflow", "cases", "inputs"]),
    ("cases", {"state": 100}, ["workflow", "cases", "flows"]),
    ("review", {}, ["workflow", "review"]),
])
def test_only_requested_stage_resources_are_read(monkeypatch, stage, weights, sections):
    """记录真实文件读取，证明分阶段加载不是把全部模板隐藏在拼接提示词里。"""
    read_text, paths = Path.read_text, []

    def record(path, *args, **kwargs):
        paths.append(path.relative_to(case_skill.SKILL_ROOT).as_posix())
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", record)
    content, loaded = case_skill.load_skill_context(stage, weights)
    assert content and loaded == sections
    assert paths == [case_skill.RESOURCE_FILES[section] for section in sections]


@pytest.mark.parametrize("section", ["../../.env", "references/design.md", "", "unknown"])
def test_skill_tool_rejects_unregistered_sections(section):
    """只接受枚举章节，绝不将模型参数直接拼为文件路径。"""
    with pytest.raises(ValueError):
        case_skill.read_skill_section(section)


def test_skill_tool_is_registered_native_and_available_to_testcase_expert():
    """真实注册入口可启动并执行只读技能，避免误走 MCP 或缺少输出契约。"""
    from app.agent import loop_wiring
    from app.harness.execution.registry import build_default_registry

    tool = build_default_registry().get("case.skill")
    assert tool.transport == "native" and tool.output_schema == {}
    assert tool.concurrency_class == "read_only" and tool.permission == "read"
    assert "case.skill" in loop_wiring.ALLOWED_TOOLS
    assert tool.handler({}, None)["skills"][0]["license"] == "MIT"
    assert "需求就绪" in tool.handler({"section": "design"}, None)["content"]


def test_upstream_files_match_pinned_import():
    """上游原件与许可保持原样，二次开发文件存放在独立目录。"""
    root = case_skill.SKILL_ROOT.parent / "upstream" / "designing-functional-tests"
    origin = json.loads((root / "ORIGIN.json").read_text(encoding="utf-8"))
    assert origin["commit"] == case_skill.UPSTREAM_COMMIT
    for filename, digest in origin["files_sha256"].items():
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == digest
    assert "MIT License" in (case_skill.SKILL_ROOT / "LICENSE").read_text(encoding="utf-8")


def test_design_source_and_selected_point_trace():
    """平台绑定原文，未知点被移除，重复用例去重，模型不能伪造需求引用。"""
    design = parse_design(design_output(), "登录需求")
    assert design["test_points"][0]["id"] == "TP-001"
    check_design_source(design, "登录需求")
    with pytest.raises(ValueError, match="来源已变化"):
        check_design_source(design, "修改后的登录需求")
    case = {"test_point_id": "TP-001", "name": "登录", "strategy": "正向", "requirement_quote": "捏造"}
    cases = trace_cases([case, case, {**case, "test_point_id": "TP-002"}, {"name": "无依据"}], design)
    assert cases == [{**case, "requirement_quote": "登录需求", "risk": "high"}]


def test_design_rejects_invented_evidence_and_duplicate_points():
    """看似正确的 JSON 也必须满足真实原文依据与唯一测试点约束。"""
    with pytest.raises(ValueError, match="原文"):
        parse_design(design_output("不存在的依据"), "登录需求")
    design = parse_design(design_output(), "登录需求")
    design["test_points"] *= 2
    with pytest.raises(ValueError, match="重复"):
        validate_design(design)


@pytest.mark.parametrize("count", range(1, 81))
def test_strategy_quotas_sum_to_requested_count(count):
    """小批量不会因六个策略各取至少一条而超过用户上限。"""
    quotas = strategy_quotas(count, STRATEGY_WEIGHTS)
    assert sum(quotas.values()) == count
    assert all(value >= 0 for value in quotas.values())
