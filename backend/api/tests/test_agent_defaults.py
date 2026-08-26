"""确认卡默认值单一源回归（defaults.py ↔ confirm_spec 预填）。"""

from app.agent.defaults import (
    DEFAULT_RAG_MODE,
    DEFAULT_RUN,
    DEFAULT_STRESS,
    DEFAULT_WITH_STRESS,
    default_task_spec,
)
from app.harness.orchestration.confirm_spec import DEFAULT_RUN as SPEC_RUN
from app.harness.orchestration.confirm_spec import DEFAULT_STRESS as SPEC_STRESS
from app.harness.orchestration.confirm_spec import build_slash_stress_spec


def test_confirm_spec_reexports_defaults() -> None:
    """拼装层不得另备第二套默认值。"""
    assert SPEC_RUN == DEFAULT_RUN
    assert SPEC_STRESS == DEFAULT_STRESS


def test_default_run_matches_prd() -> None:
    """PRD §5.2.2：抽样上限 1000、并发 4、超时 60、K=5。"""
    assert DEFAULT_RUN["sample_size"] == 1000
    assert DEFAULT_RUN["concurrency"] == 4
    assert DEFAULT_RUN["timeout_s"] == 60
    assert DEFAULT_RUN["k"] == 5
    assert DEFAULT_RUN["use_judge"] is False


def test_default_task_spec_skeleton() -> None:
    """确认卡骨架含 kind/run/stress，资产 ID 留空由用户补齐。"""
    spec = default_task_spec("benchmark")
    assert spec["kind"] == "benchmark"
    assert spec["profile_ids"] == []
    assert spec["dataset_id"] is None
    assert spec["run"]["sample_size"] == 1000
    assert spec["with_stress"] is DEFAULT_WITH_STRESS
    assert spec["rag_mode"] == DEFAULT_RAG_MODE
    assert spec["stress"]["env"] == "test"


def test_slash_stress_spec_never_kind_stress() -> None:
    """/stress 必须是质量任务卡且 with_stress=true，禁止 kind=stress。"""
    spec = build_slash_stress_spec({"last_kind": "stress", "last_with_stress": False})
    assert spec["kind"] == "benchmark"
    assert spec["with_stress"] is True
    rag = build_slash_stress_spec(
        {
            "last_kind": "rag",
            "last_kb_id": "kb-1",
            "last_gold_qa_id": "qa-1",
            "last_profile_ids": ["p-1"],
        }
    )
    assert rag["kind"] == "rag"
    assert rag["with_stress"] is True
    assert rag["kb_id"] == "kb-1"
    assert rag["gold_qa_id"] == "qa-1"
    assert rag["profile_ids"] == ["p-1"]
    testcase = build_slash_stress_spec({"last_kind": "testcase"})
    assert testcase["kind"] == "benchmark"
    assert testcase["with_stress"] is True
