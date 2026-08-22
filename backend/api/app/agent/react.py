"""行动阶段：产品规格组装 + 再导出 Harness 单调用循环。

工作流对齐 Claude Code / Cursor：每轮先出思考卡，再调用一个内部 MCP 短工具，
观察结果后进入下一轮。长任务不得在循环内执行。
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agent.defaults import REQUIRED_SLOTS, default_run, default_stress
from app.agent.imagegen import looks_like_image_generation
from app.agent.log import agent_trace
from app.agent.plan import PlanArtifact, sanitize_plan
from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.trace import TraceContext
from app.harness.execution.facade import execute_short_tool
from app.harness.orchestration.parser import McpStep, parse_mcp_step
from app.harness.orchestration.react_loop import (
    emit_and_run_tool,
    execute_short_tool_isolated,
    run_react_loop,
    stream_mcp_step,
)

__all__ = [
    "McpStep",
    "ReactArtifact",
    "apply_replan",
    "build_proposed_spec",
    "execute_short_tool",
    "match_named_ids",
    "parse_mcp_step",
    "run_react",
]

EmitFn = Callable[..., Awaitable[int]]
AbortCheck = Callable[[], None]

_EVAL_INVENTORY_TOOLS = frozenset({"model.list", "dataset.list", "kb.list"})

# 测试与适配别名：必须挂在本模块上供 monkeypatch。
_stream_mcp_step = stream_mcp_step


def _redirect_creative_tool(plan: PlanArtifact, text: str, name: str | None) -> str | None:
    """生图/配音回合拦截协议档、数据集清单，改回本轮真正需要的短工具。"""
    if not name or name not in _EVAL_INVENTORY_TOOLS:
        return name
    tools = list(plan.tools_needed or [])
    if not (
        "image.generate" in tools
        or "audio.voiceclone" in tools
        or looks_like_image_generation(text)
    ):
        return name
    agent_trace(f"ReAct 拦截评测清单工具 name={name}")
    if "image.generate" in tools or looks_like_image_generation(text):
        return "image.generate"
    if "audio.voiceclone" in tools:
        return "audio.voiceclone"
    return None


@dataclass
class ReactArtifact:
    """行动产物。"""

    observations: list[dict[str, Any]] = field(default_factory=list)
    proposed_spec: dict[str, Any] | None = None
    known_ids: list[str] = field(default_factory=list)
    pref_stale_notes: list[str] = field(default_factory=list)
    rounds_used: int = 0
    reply_text: str = ""
    thinking_text: str = ""
    used_llm: bool = False

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
            (
                item
                for item in items
                if item.get("id") == name
                or name in str(item.get("name") or "")
                or str(item.get("name") or "") in name
            ),
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


def _execute_short_tool_isolated(
    name: str,
    arguments: dict,
    user_id: str,
) -> tuple[bool, Any, str | None, int]:
    """耗时短工具用独立会话在线程里跑；执行函数取本模块可 patch 的名字。"""
    return execute_short_tool_isolated(
        name,
        arguments,
        user_id,
        execute_short_tool=execute_short_tool,
    )


_execute_short_tool_isolated._harness_native = True  # type: ignore[attr-defined]


async def _emit_and_run_tool(
    db: Session,
    react: ReactArtifact,
    *,
    name: str,
    arguments: dict[str, Any],
    user_id: str,
    emit: EmitFn,
    text: str,
    attachments: list[str],
    trace: TraceContext,
    cancel: CancellationToken,
) -> bool:
    """兼容旧内部调用；执行与观察走 Harness 循环。"""
    return await emit_and_run_tool(
        db,
        react,
        name=name,
        arguments=arguments,
        user_id=user_id,
        emit=emit,
        text=text,
        attachments=attachments,
        execute_short_tool=execute_short_tool,
        execute_isolated=_execute_short_tool_isolated,
        trace=trace,
        cancel=cancel,
    )


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
    use_llm: bool = False,
    stop: threading.Event | None = None,
    history: list[dict[str, str]] | None = None,
    compact_summary: str | None = None,
    trace: TraceContext,
    cancel: CancellationToken,
) -> ReactArtifact:
    """ReAct 行动：优先 MCP JSON 多轮循环，失败则按 tools_needed 串行。

    ``trace`` / ``cancel`` 由 dispatch 注入，测试夹具必须显式构造，禁止默认 ``for_turn()``。
    """
    return await run_react_loop(
        db,
        plan,
        user_id=user_id,
        emit=emit,
        check_abort=check_abort,
        slash_fill_first=slash_fill_first,
        prior=prior,
        extra_tools=extra_tools,
        text=text,
        attachments=attachments,
        use_llm=use_llm,
        stop=stop or cancel.stop,
        history=history,
        compact_summary=compact_summary,
        stream_mcp_step=_stream_mcp_step,
        execute_short_tool=execute_short_tool,
        execute_isolated=_execute_short_tool_isolated,
        new_artifact=ReactArtifact,
        redirect_creative_tool=_redirect_creative_tool,
        missing_for_kind=_missing_for_kind,
        build_proposed_spec=build_proposed_spec,
        trace=trace,
        cancel=cancel,
    )


def apply_replan(raw: dict, plan: PlanArtifact) -> PlanArtifact:
    """补规划：根据观察调整 tools_needed 或改判 delivery=clarify。不得开第二轮。"""
    extra = sanitize_plan({**plan.as_dict(), **raw}, source="replan")
    extra.used_model = True
    return extra
