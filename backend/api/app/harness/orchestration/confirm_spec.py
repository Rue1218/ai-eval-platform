"""从规划产物拼装对话确认卡 TaskSpec（API.md §5）。

LangGraph reflect 在 ``delivery=confirm`` 且复核通过后发出 ``confirm`` 事件；
卡标必须是可编辑的 TaskSpec，缺数据集/协议档由用户在确认卡上补齐，不得把
``kind`` 设为 ``stress``（压测由质量任务 ``with_stress`` 派生）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.errors import AppError
from app.harness.contracts import Observation, PlanArtifact, from_dict
from app.harness.skills import skill_to_kind

# 与 PRD 5.2.2 / API.md §5 / frontend confirmCard.ts 同一份默认值
DEFAULT_RUN: dict[str, Any] = {
    "sample_size": 1000,
    "concurrency": 4,
    "timeout_s": 60,
    "retry": 1,
    "temperature": 0,
    "max_tokens": 1024,
    "system_prompt": "",
    "k": 5,
    "use_judge": False,
}

DEFAULT_STRESS: dict[str, Any] = {
    "env": "test",
    "qps": 10,
    "duration_s": 120,
    "sla_p99_ms": None,
}

_QUALITY_KINDS = frozenset({"benchmark", "rag", "testcase"})


def _plain_slots(slots: Mapping[str, object] | None) -> dict[str, Any]:
    """把规划槽位转为可写 dict，忽略非映射。"""
    if not isinstance(slots, Mapping):
        return {}
    return {str(key): value for key, value in slots.items()}


def _looks_ref(value: object) -> str | None:
    """接受平台 ID（UUID 或 seed 短名），拒绝中文说明句。"""
    text = str(value or "").strip()
    if not text or len(text) > 64:
        return None
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return None
    if any(ch.isspace() for ch in text):
        return None
    return text


def _as_id_list(value: object) -> list[str]:
    """把槽位/观察里的协议档 ID 归一为 1–5 个字符串。"""
    items: Sequence[object]
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        items = value
    else:
        return []
    refs: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            raw = item.get("id") or item.get("profile_id")
        else:
            raw = item
        ref = _looks_ref(raw)
        if ref and ref not in refs:
            refs.append(ref)
        if len(refs) >= 5:
            break
    return refs


def _blob(plan: PlanArtifact) -> str:
    """意图/备注/步骤拼成小写检索串，用于多技能 kind 判定。"""
    steps = plan.slots.get("steps") if isinstance(plan.slots, Mapping) else None
    step_text = " ".join(str(item) for item in steps) if isinstance(steps, list) else ""
    return f"{plan.intent} {plan.notes} {plan.skill_id or ''} {step_text}".lower()


def kind_from_plan(plan: PlanArtifact) -> str | None:
    """规划 → 确认卡 kind；``skill-stress`` 收成 benchmark（先评后压）。"""
    if plan.skill_id:
        try:
            mapped = skill_to_kind(plan.skill_id)
        except AppError:
            mapped = None
        if mapped == "stress":
            return "benchmark"
        if mapped in _QUALITY_KINDS:
            return mapped
    blob = _blob(plan)
    if "知识库" in plan.intent or "rag" in blob:
        if "基准" in plan.intent or "benchmark" in blob:
            return "benchmark"
        return "rag"
    if ("用例" in plan.intent or "testcase" in blob) and (
        "评测" not in plan.intent and "benchmark" not in blob
    ):
        return "testcase"
    if any(token in blob for token in ("评测", "benchmark", "压测", "stress")):
        return "benchmark"
    if "用例" in plan.intent or "testcase" in blob:
        return "testcase"
    return None


def wants_stress(plan: PlanArtifact) -> bool:
    """规划是否勾选先评后压（对话路径不得直接 kind=stress）。"""
    if plan.skill_id == "skill-stress":
        return True
    blob = _blob(plan)
    return any(
        token in blob
        for token in ("压测", "stress", "先评后压", "先评再压", "评完再压")
    )


def _merge_run(slots: dict[str, Any]) -> dict[str, Any]:
    """默认 run 与规划槽位里的 run 深合并。"""
    run = dict(DEFAULT_RUN)
    raw = slots.get("run")
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if key in run and value is not None:
                run[str(key)] = value
    return run


def _merge_stress(slots: dict[str, Any]) -> dict[str, Any]:
    """默认压测段与规划槽位合并。"""
    stress = dict(DEFAULT_STRESS)
    raw = slots.get("stress")
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if key in stress and value is not None:
                stress[str(key)] = value
    return stress


def _observations(raw: object) -> list[Observation]:
    """从 GraphState.observations 抽出合法 Observation。"""
    if not isinstance(raw, list):
        return []
    items: list[Observation] = []
    for entry in raw:
        if isinstance(entry, Observation):
            items.append(entry)
            continue
        if isinstance(entry, dict):
            try:
                items.append(from_dict(Observation, dict(entry)))
            except ValueError:
                continue
    return items


def _prefill_from_observations(spec: dict[str, Any], observations: list[Observation]) -> None:
    """用短工具列表结果预填 ID；只补空槽，不覆盖规划已给的值。"""
    for obs in observations:
        data = obs.display_data if isinstance(obs.display_data, Mapping) else {}
        items = data.get("items")
        if not isinstance(items, list) or not items:
            continue
        tool = (obs.tool or "").lower()
        if not spec.get("dataset_id") and "dataset" in tool:
            ref = _looks_ref(
                items[0].get("id") if isinstance(items[0], Mapping) else None
            )
            if ref:
                spec["dataset_id"] = ref
        if not spec.get("profile_ids") and (
            "model" in tool or "profile" in tool
        ):
            spec["profile_ids"] = _as_id_list(items)
        if spec.get("kind") == "rag":
            if not spec.get("kb_id") and "kb" in tool:
                ref = _looks_ref(
                    items[0].get("id") if isinstance(items[0], Mapping) else None
                )
                if ref:
                    spec["kb_id"] = ref
            if not spec.get("gold_qa_id") and "gold" in tool:
                ref = _looks_ref(
                    items[0].get("id") if isinstance(items[0], Mapping) else None
                )
                if ref:
                    spec["gold_qa_id"] = ref


def build_confirm_payload(
    plan: PlanArtifact,
    observations: object | None = None,
) -> dict[str, Any] | None:
    """拼装确认卡 payload；无法判定质量任务 kind 时返回 None（不发卡）。

    缺 ``dataset_id`` / ``profile_ids`` 等必填项仍发卡：确认卡本身就是补槽位的
    UI。``kind=stress`` 永不出现。
    """
    kind = kind_from_plan(plan)
    if kind not in _QUALITY_KINDS:
        return None
    slots = _plain_slots(plan.slots)
    spec: dict[str, Any] = {
        "kind": kind,
        "profile_ids": _as_id_list(slots.get("profile_ids")),
        "dataset_id": _looks_ref(slots.get("dataset_id")),
        "kb_id": _looks_ref(slots.get("kb_id")),
        "gold_qa_id": _looks_ref(slots.get("gold_qa_id")),
        "rag_mode": ["hybrid"],
        "run": _merge_run(slots),
        "with_stress": False,
        "stress": _merge_stress(slots),
    }
    modes = slots.get("rag_mode")
    if isinstance(modes, list) and modes:
        spec["rag_mode"] = [str(item) for item in modes if item][:4] or ["hybrid"]
    case_source = slots.get("case_source")
    if isinstance(case_source, Mapping):
        spec["case_source"] = dict(case_source)
    if kind in {"benchmark", "rag"} and wants_stress(plan):
        spec["with_stress"] = True
    _prefill_from_observations(spec, _observations(observations))
    return spec
