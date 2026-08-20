"""行动阶段：按 tools_needed 串行执行短工具（HAR-ACT）。

M1 阶段 ReAct 0 次模型调用；工具跑完仍缺槽允许 1 次补规划。
只读工具默认串行；写工具永远串行。禁止用幻觉 ID 填槽。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from .defaults import (
    DEFAULT_TOOL_ROUNDS,
    HARD_MAX_TOOL_ROUNDS,
    PARALLEL_READONLY_TOOLS,
    REQUIRED_SLOTS,
    SHORT_TOOLS,
    default_run,
    default_stress,
    is_long_tool,
)
from .log import agent_trace
from .long_tasks import assert_short_tool
from .mcp_tools import collect_ids, execute_short_tool, summarize_observation
from .plan import PlanArtifact, sanitize_plan
from .voiceclone import arguments_for_voiceclone

EmitFn = Callable[..., Awaitable[int]]
AbortCheck = Callable[[], None]


@dataclass
class ReactArtifact:
    """行动产物。"""

    observations: list[dict[str, Any]] = field(default_factory=list)
    proposed_spec: dict[str, Any] | None = None
    known_ids: list[str] = field(default_factory=list)
    pref_stale_notes: list[str] = field(default_factory=list)
    # 已消耗的工具轮次（含跳过/失败），补规划续跑时计入同一硬顶
    rounds_used: int = 0

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"observations": list(self.observations)}
        if self.proposed_spec is not None:
            body["proposed_spec"] = dict(self.proposed_spec)
        return body


def _deep_merge(base: dict, patch: dict) -> dict:
    """嵌套对象递归覆盖，数组整段替换。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def match_named_ids(items: list[dict], names: list[str]) -> list[str]:
    """按名称/ID 从本轮 list 结果中挑选；未命中不回退到首个（禁止幻觉）。"""
    picked: list[str] = []
    for name in names:
        if not name:
            continue
        hit = next(
            (item for item in items if item.get("id") == name or name in str(item.get("name") or "") or str(item.get("name") or "") in name),
            None,
        )
        if hit and hit["id"] not in picked:
            picked.append(hit["id"])
    return picked


def _items_of(observations: list[dict], tool_name: str) -> list[dict]:
    """从成功的 list 观察中还原 items 已不可得，仅有 ids；此处用 data_summary。"""
    for obs in observations:
        if obs.get("name") == tool_name and obs.get("ok"):
            ids = (obs.get("data_summary") or {}).get("ids") or []
            names = (obs.get("data_summary") or {}).get("names") or []
            return [
                {"id": iid, "name": names[idx] if idx < len(names) else iid}
                for idx, iid in enumerate(ids)
            ]
    return []


def _slot_filled(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        if "file_id" in value or "text" in value:
            text = str(value.get("text") or "").strip()
            return bool(value.get("file_id") or text)
        return bool(value)
    return True


def _missing_for_kind(spec: dict[str, Any]) -> list[str]:
    kind = spec.get("kind")
    missing = [key for key in REQUIRED_SLOTS.get(kind, ()) if not _slot_filled(spec.get(key))]
    if spec.get("with_stress") and not spec.get("stress"):
        missing.append("stress")
    return missing


def build_proposed_spec(plan: PlanArtifact, react: ReactArtifact, *, slash_fill_first: bool) -> dict[str, Any] | None:
    """用规划 filled + 本轮工具 ID 组装 proposed_spec；ID 必须来自观察。"""
    intent = plan.intent
    if intent not in {"benchmark", "rag", "testcase", "rerun"}:
        return None
    filled = deepcopy(plan.slots.get("filled") or {})
    kind = filled.get("kind") or (intent if intent != "rerun" else "benchmark")
    if kind == "stress":
        kind = "benchmark"
    spec: dict[str, Any] = {"kind": kind}
    known = set(react.known_ids)

    profile_items = _items_of(react.observations, "model.list")
    dataset_items = _items_of(react.observations, "dataset.list")

    wanted_profiles = filled.get("profile_ids") or []
    if isinstance(wanted_profiles, str):
        wanted_profiles = [wanted_profiles]
    valid_profiles = [pid for pid in wanted_profiles if pid in known]
    stale_profiles = [pid for pid in wanted_profiles if pid and pid not in known]
    if stale_profiles and profile_items:
        note = "上次的协议档已删除"
        if note not in react.pref_stale_notes:
            react.pref_stale_notes.append(note)
    if not valid_profiles and slash_fill_first and profile_items:
        valid_profiles = [profile_items[0]["id"]]
    if valid_profiles:
        spec["profile_ids"] = valid_profiles[:5]

    wanted_dataset = filled.get("dataset_id")
    if wanted_dataset and wanted_dataset in known:
        spec["dataset_id"] = wanted_dataset
    elif wanted_dataset and dataset_items:
        note = "上次的数据集已删除"
        if note not in react.pref_stale_notes:
            react.pref_stale_notes.append(note)
    elif slash_fill_first and dataset_items:
        spec["dataset_id"] = dataset_items[0]["id"]

    if kind == "testcase":
        if filled.get("case_source"):
            spec["case_source"] = filled["case_source"]

    spec["run"] = _deep_merge(default_run(), filled.get("run") if isinstance(filled.get("run"), dict) else {})
    if kind in {"benchmark", "rag"}:
        spec["with_stress"] = bool(filled.get("with_stress"))
        if spec["with_stress"]:
            spec["stress"] = _deep_merge(
                default_stress(),
                filled.get("stress") if isinstance(filled.get("stress"), dict) else {},
            )
    else:
        spec["with_stress"] = False
    if kind == "rag":
        spec["rag_mode"] = filled.get("rag_mode") or ["hybrid"]
        if filled.get("kb_id") in known:
            spec["kb_id"] = filled["kb_id"]
        if filled.get("gold_qa_id") in known:
            spec["gold_qa_id"] = filled["gold_qa_id"]

    missing = _missing_for_kind(spec)
    plan.slots["missing"] = missing
    if missing and plan.delivery == "confirm" and plan.source != "slash":
        pass
    return spec


async def run_react(
    db: Session,
    plan: PlanArtifact,
    *,
    user_id: str,
    emit: EmitFn,
    check_abort: AbortCheck,
    slash_fill_first: bool,
    prior: ReactArtifact | None = None,
    extra_tools: list[str] | None = None,
    text: str = "",
    attachments: list[str] | None = None,
) -> ReactArtifact:
    """串行执行短工具，发出成对 tool_call / tool_result。

    ``prior`` + ``extra_tools`` 用于补规划后继续执行尚未跑过的工具，
    轮次计入同一 ``max_tool_rounds`` 硬顶（默认 4，硬顶 5）。
    ``text`` / ``attachments`` 仅 ``audio.voiceclone`` 使用，file_id 取自本轮附件。
    """
    react = prior or ReactArtifact()
    # 预留并行开关：M1 强制串行，打开后仍须保证事件成对
    _ = PARALLEL_READONLY_TOOLS
    rounds_cap = min(int(plan.budget.get("max_tool_rounds") or DEFAULT_TOOL_ROUNDS), HARD_MAX_TOOL_ROUNDS)
    queue = list(extra_tools if extra_tools is not None else plan.tools_needed)
    executed = react.rounds_used
    turn_attachments = list(attachments or [])

    if not queue:
        react.proposed_spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        return react

    while queue and executed < rounds_cap:
        check_abort()
        name = queue.pop(0)
        executed += 1
        if is_long_tool(name):
            assert_short_tool(name)  # 抛 VALIDATION
        if name not in SHORT_TOOLS and not is_long_tool(name):
            agent_trace(f"跳过未知工具 name={name}")
            continue
        if name == "task.create":
            # 写工具永远串行，且 create 只在 ack 后；ReAct 中拒绝
            await emit("tool_call", {"name": name, "arguments": {}})
            await emit(
                "tool_result",
                {"name": name, "ok": False, "error": "task.create 只允许在确认卡 ack 之后执行", "latency_ms": 0},
            )
            react.observations.append(
                summarize_observation(name, False, None, "task.create 只允许在确认卡 ack 之后执行", 0)
            )
            continue

        arguments: dict[str, Any] = {}
        if name == "audio.voiceclone":
            arguments = arguments_for_voiceclone(db, text=text, attachments=turn_attachments)
        await emit("tool_call", {"name": name, "arguments": arguments})
        if name == "audio.voiceclone":
            ok, data, error, latency_ms = await asyncio.to_thread(
                _execute_short_tool_isolated,
                name,
                arguments,
                user_id,
            )
        else:
            ok, data, error, latency_ms = execute_short_tool(
                db, name, arguments, user_id=user_id, allow_create=False
            )
        payload: dict[str, Any] = {"name": name, "ok": ok, "latency_ms": latency_ms}
        if ok:
            payload["data"] = data
            react.known_ids.extend(collect_ids(data))
        else:
            payload["error"] = error or "该能力未启用"
        await emit("tool_result", payload)
        react.observations.append(summarize_observation(name, ok, data, error, latency_ms))

        spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        react.proposed_spec = spec
        if spec and not _missing_for_kind(spec):
            break
        if not ok:
            # 单工具失败：记入观察，无替代则进入复核 clarify
            break

    react.rounds_used = executed
    if executed >= rounds_cap and queue:
        agent_trace(f"工具轮次达到硬顶 rounds={executed}")
    if react.proposed_spec is None:
        react.proposed_spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
    return react


def _execute_short_tool_isolated(
    name: str,
    arguments: dict,
    user_id: str,
) -> tuple[bool, Any, str | None, int]:
    """耗时短工具用独立会话在线程里跑，避免阻塞事件循环时共用 Harness 会话。"""
    from ..db import SessionLocal

    isolated = SessionLocal()
    try:
        return execute_short_tool(isolated, name, arguments, user_id=user_id, allow_create=False)
    finally:
        isolated.close()


def apply_replan(raw: dict, plan: PlanArtifact) -> PlanArtifact:
    """补规划：根据观察调整 tools_needed 或改判 delivery=clarify。不得开第二轮。"""
    extra = sanitize_plan({**plan.as_dict(), **raw}, source="replan")
    extra.used_model = True
    return extra
