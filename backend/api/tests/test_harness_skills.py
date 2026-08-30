"""M10 技能体系单测（K-A1~K-A5）；不依赖 DB/WS。"""

from pathlib import Path

import pytest

from app.errors import AppError, ErrorCode
from app.harness.context import assemble, skill_hint_lines, skill_hints_for_turn
from app.harness.skills import (
    DISABLED_SKILLS,
    SKILL_CATALOG,
    assert_skill_enabled,
    list_hints,
    load_skill_workflow,
    skill_to_kind,
)
from app.harness.skills.storage import (
    ensure_skill_files,
    read_skill_document,
    read_skill_metadata,
    update_skill_document,
)

_FRONTEND_LABELS = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "agent" / "skillLabels.ts"
)


def test_skill_catalog_has_four_hints() -> None:
    """K-A1：4 个 SkillHint 常驻。"""
    hints = list_hints()
    assert {hint.skill_id for hint in hints} == set(SKILL_CATALOG)
    assert len(hints) == 4


def test_skill_hints_only_name_and_summary_no_full_doc() -> None:
    """K-A1：常驻 Hint 只有名称 + 一句话，不含完整工作流正文。"""
    joined = "\n".join(skill_hint_lines())
    assert "基准评测" in joined
    assert "三协议调用" not in joined
    assert "六策略 LLM" not in joined
    assert "kind=stress" not in joined
    assert "【当前技能工作流】" not in joined


def test_adjacent_turns_skill_injection_no_pollution() -> None:
    """K-A2：相邻回合只注入当前选中技能的 Hint + 工作流，互不污染。"""
    turn_a = assemble(
        system="Persona",
        skill_hints=skill_hints_for_turn("skill-benchmark"),
        skill_workflow=load_skill_workflow("skill-benchmark"),
        messages=[{"role": "user", "content": "评测"}],
    )
    turn_b = assemble(
        system="Persona",
        skill_hints=skill_hints_for_turn("skill-testcase"),
        skill_workflow=load_skill_workflow("skill-testcase"),
        messages=[{"role": "user", "content": "用例"}],
    )
    assert "三协议调用" in turn_a["system"]
    assert "六策略 LLM" not in turn_a["system"]
    assert "用例生成" not in turn_a["system"]
    assert "六策略 LLM" in turn_b["system"]
    assert "三协议调用" not in turn_b["system"]
    assert "基准评测" not in turn_b["system"]
    catalog = assemble(
        system="Persona",
        skill_hints=skill_hints_for_turn(),
        messages=[{"role": "user", "content": "你好"}],
    )
    assert "【当前技能工作流】" not in catalog["system"]
    assert "三协议调用" not in catalog["system"]


def test_skill_kind_map_one_to_one() -> None:
    """K-A3：skill_id ↔ kind 1:1。"""
    kinds = {skill_to_kind(skill_id) for skill_id in SKILL_CATALOG}
    assert kinds == {"benchmark", "testcase", "rag", "stress"}
    assert len(kinds) == len(SKILL_CATALOG)


def test_skill_rag_disabled_raises_validation() -> None:
    """K-A4：skill-rag 未接入抛 VALIDATION，不得加载工作流正文。"""
    assert "skill-rag" in DISABLED_SKILLS
    with pytest.raises(AppError) as error:
        assert_skill_enabled("skill-rag")
    assert error.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError) as error:
        load_skill_workflow("skill-rag")
    assert error.value.code == ErrorCode.VALIDATION
    document = read_skill_document("skill-rag")
    assert document.metadata.enabled is False


def test_skill_file_requires_existence_before_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """技能读取先验证 SKILL.md 存在；空运行时目录不得回退硬编码正文。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    with pytest.raises(AppError) as error:
        read_skill_metadata("skill-benchmark")
    assert error.value.code == ErrorCode.NOT_FOUND


def test_skill_file_header_and_workflow_are_loaded_in_two_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """目录仅使用头部字段，完整工作流只在明确读取单个技能时加载。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    metadata = read_skill_metadata("skill-benchmark")
    document = read_skill_document("skill-benchmark")
    assert metadata.summary == "执行大模型基准评测"
    assert document.content.startswith("---\nid: skill-benchmark\n")
    assert "## 工作流" in document.content


def test_skill_file_edit_rejects_stale_revision_and_enabling_rag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """编辑必须携带当前修订指纹，且未接入 RAG 不得通过文件绕过启用门禁。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    benchmark = read_skill_document("skill-benchmark")
    with pytest.raises(AppError) as stale:
        update_skill_document("skill-benchmark", benchmark.content, "stale-revision-00")
    assert stale.value.code == ErrorCode.CONCURRENCY

    rag = read_skill_document("skill-rag")
    with pytest.raises(AppError) as invalid:
        update_skill_document(
            "skill-rag",
            rag.content.replace("enabled: false", "enabled: true"),
            rag.revision,
        )
    assert invalid.value.code == ErrorCode.VALIDATION


def test_skill_file_edit_rejects_suspected_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skill 正文不得保存疑似凭据，且校验失败不能覆盖现有文件。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    benchmark = read_skill_document("skill-benchmark")
    unsafe_content = benchmark.content.replace("## 工作流", "password: should-not-save\n\n## 工作流")

    with pytest.raises(AppError) as error:
        update_skill_document("skill-benchmark", unsafe_content, benchmark.revision)

    assert error.value.code == ErrorCode.VALIDATION
    assert read_skill_document("skill-benchmark").content == benchmark.content


def test_skill_list_matches_slash_commands() -> None:
    """K-A5：后端技能清单与前端 skillLabels.ts 的 4 个 skill_id 一致。"""
    text = _FRONTEND_LABELS.read_text(encoding="utf-8")
    for skill_id, (name, summary, _kind) in SKILL_CATALOG.items():
        assert skill_id in text
        assert summary in text
        assert name  # 目录名称非空；前端展示用徽标文案，不强制等于 name
