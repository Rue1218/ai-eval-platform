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


def test_skill_catalog_only_exposes_testcase_hint() -> None:
    """K-A1：仅用例生成进入运行时 Hint，停用技能仍保留历史目录定义。"""
    hints = list_hints()
    assert {hint.skill_id for hint in hints} == {"skill-testcase"}
    assert set(SKILL_CATALOG) - DISABLED_SKILLS == {"skill-testcase"}


def test_skill_hints_only_name_and_summary_no_full_doc() -> None:
    """K-A1：常驻 Hint 只有名称 + 一句话，不含完整工作流正文。"""
    joined = "\n".join(skill_hint_lines())
    assert "用例生成" in joined
    assert "基准评测" not in joined
    assert "两类协议调用" not in joined
    assert "六策略 LLM" not in joined
    assert "kind=stress" not in joined
    assert "【当前技能工作流】" not in joined


def test_adjacent_turns_skill_injection_no_pollution() -> None:
    """K-A2：相邻回合只注入当前选中技能的 Hint + 工作流，互不污染。"""
    turn_a = assemble(
        system="Persona",
        skill_hints=skill_hints_for_turn("skill-testcase"),
        skill_workflow=load_skill_workflow("skill-testcase"),
        messages=[{"role": "user", "content": "生成用例"}],
    )
    turn_b = assemble(
        system="Persona",
        skill_hints=skill_hints_for_turn(),
        messages=[{"role": "user", "content": "你好"}],
    )
    assert "【当前技能工作流】" in turn_a["system"]
    assert "用例" in turn_a["system"]
    assert "【当前技能工作流】" not in turn_b["system"]
    assert "基准评测" not in turn_b["system"]


def test_active_skill_kind_is_testcase() -> None:
    """K-A3：运行时启用技能只映射用例任务。"""
    assert {skill_to_kind(hint.skill_id) for hint in list_hints()} == {"testcase"}


@pytest.mark.parametrize("skill_id", ["skill-benchmark", "skill-rag", "skill-stress"])
def test_retired_skills_raise_validation(skill_id: str) -> None:
    """K-A4：旧技能保留读取兼容，但不能加载工作流或恢复执行。"""
    assert skill_id in DISABLED_SKILLS
    with pytest.raises(AppError) as error:
        assert_skill_enabled(skill_id)
    assert error.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError) as error:
        load_skill_workflow(skill_id)
    assert error.value.code == ErrorCode.VALIDATION
    assert read_skill_document(skill_id).metadata.enabled is False


def test_skill_file_requires_existence_before_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """技能读取先验证 SKILL.md 存在；空运行时目录不得回退硬编码正文。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    with pytest.raises(AppError) as error:
        read_skill_metadata("skill-testcase")
    assert error.value.code == ErrorCode.NOT_FOUND


def test_skill_file_header_and_workflow_are_loaded_in_two_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """目录仅使用头部字段，完整工作流只在明确读取单个技能时加载。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    metadata = read_skill_metadata("skill-testcase")
    document = read_skill_document("skill-testcase")
    assert metadata.summary == "根据需求生成待确认测试用例"
    assert document.content.startswith("---\nid: skill-testcase\n")
    assert "## 工作流" in document.content


def test_skill_file_edit_rejects_stale_revision_and_enabling_rag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """编辑须携带当前指纹；禁用技能不得通过改文件重新启用。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    benchmark = read_skill_document("skill-benchmark")
    with pytest.raises(AppError) as stale:
        update_skill_document("skill-benchmark", benchmark.content, "stale-revision-00")
    assert stale.value.code == ErrorCode.CONCURRENCY

    rag = read_skill_document("skill-rag")
    with pytest.raises(AppError) as invalid:
        update_skill_document(
            "skill-rag", rag.content.replace("enabled: false", "enabled: true"), rag.revision,
        )
    assert invalid.value.code == ErrorCode.VALIDATION
    assert read_skill_document("skill-rag").metadata.enabled is False
    with pytest.raises(AppError) as error:
        load_skill_workflow("skill-rag")
    assert error.value.code == ErrorCode.VALIDATION


def test_skill_file_edit_rejects_suspected_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skill 正文不得保存疑似凭据，且校验失败不能覆盖现有文件。"""
    monkeypatch.setenv("AGENT_SKILLS_ROOT", str(tmp_path / "skills"))
    ensure_skill_files()
    testcase = read_skill_document("skill-testcase")
    unsafe_content = testcase.content.replace("## 工作流", "password: should-not-save\n\n## 工作流")

    with pytest.raises(AppError) as error:
        update_skill_document("skill-testcase", unsafe_content, testcase.revision)

    assert error.value.code == ErrorCode.VALIDATION
    assert read_skill_document("skill-testcase").content == testcase.content


def test_active_skill_has_frontend_label() -> None:
    """K-A5：启用的用例技能在前端保留可识别标签。"""
    text = _FRONTEND_LABELS.read_text(encoding="utf-8")
    assert "skill-testcase" in text
    assert SKILL_CATALOG["skill-testcase"][0] == "用例生成"
