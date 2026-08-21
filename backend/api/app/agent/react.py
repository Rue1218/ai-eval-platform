"""行动阶段：MCP 短工具的 Think-Act-Observe 循环（HAR-ACT）。

工作流对齐 Claude Code / Cursor：每轮先出思考卡，再调用一个内部 MCP 短工具，
观察结果后进入下一轮。禁止 OpenAI function calling；工具名走 ``mcp_tools`` 白名单。

长任务（benchmark.run / rag.evaluate / testcase.generate / stress.run）不得在
循环内执行，槽位齐后交给确认卡 → Worker 入队。模型不可用时回退 ``tools_needed`` 队列。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..errors import AppError
from .defaults import (
    DEFAULT_TOOL_ROUNDS,
    HARD_MAX_TOOL_ROUNDS,
    MODEL_TIMEOUT_S,
    PARALLEL_READONLY_TOOLS,
    REQUIRED_SLOTS,
    SHORT_TOOLS,
    TOOL_TIMEOUTS,
    TOOL_TITLES,
    WRITE_TOOLS,
    default_run,
    default_stress,
    is_long_tool,
)
from .imagegen import looks_like_image_generation
from .log import agent_exception, agent_trace
from .mcp_registry import bind_tool_arguments, get_tool_definition
from .mcp_tools import collect_ids, execute_short_tool, redact_secrets, summarize_observation
from .persona import react_system, turn_system
from .plan import PlanArtifact, parse_json_object, sanitize_plan

EmitFn = Callable[..., Awaitable[int]]
AbortCheck = Callable[[], None]

_EVAL_INVENTORY_TOOLS = frozenset({"model.list", "dataset.list", "kb.list"})


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
    # 已消耗的工具轮次（含跳过/失败），补规划续跑时计入同一硬顶
    rounds_used: int = 0
    # LLM ReAct 最后一轮的可见回复与思考链；闲聊交付优先用 reply_text
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


def _bind_tool_arguments(
    db: Session,
    name: str,
    arguments: dict[str, Any],
    *,
    text: str,
    attachments: list[str],
) -> dict[str, Any]:
    """委托统一注册表绑定模型入参与本轮附件。"""
    return bind_tool_arguments(db, name, arguments, text=text, attachments=attachments)


def _executed_names(react: ReactArtifact) -> set[str]:
    """本轮已发出的工具名（含失败），用于回退队列去重。"""
    return {str(obs.get("name") or "") for obs in react.observations if obs.get("name")}


def _trace_toolcall_args(arguments: dict[str, Any]) -> str:
    """控制台打印用的入参摘要；脱敏且截断。"""
    try:
        return json.dumps(redact_secrets(arguments or {}), ensure_ascii=False)[:800]
    except Exception:
        return "{}"


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
) -> bool:
    """发出成对 tool_call / tool_result 并写入观察。返回工具是否成功。"""
    if is_long_tool(name):
        error = f"「{name}」是长任务，只能入队后由 Worker 执行"
        await emit("tool_call", {"name": name, "arguments": {}})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(summarize_observation(name, False, None, error, 0))
        agent_trace(f"ToolCall 拒绝长任务 name={name}")
        return False
    if name not in SHORT_TOOLS:
        error = f"未知短工具「{name}」"
        await emit("tool_call", {"name": name, "arguments": arguments})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(summarize_observation(name, False, None, error, 0))
        agent_trace(f"ToolCall 拒绝未知工具 name={name}")
        return False
    if name == "task.create":
        error = "task.create 只允许在确认卡 ack 之后执行"
        await emit("tool_call", {"name": name, "arguments": {}})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(summarize_observation(name, False, None, error, 0))
        agent_trace("ToolCall 拒绝 task.create（须 ack 后）")
        return False

    bound = _bind_tool_arguments(db, name, arguments, text=text, attachments=attachments)
    agent_trace(f"ToolCall 开始 name={name} arguments={_trace_toolcall_args(bound)}")
    await emit("tool_call", {"name": name, "arguments": bound})
    definition = get_tool_definition(name)
    timeout_sec = definition.timeout_s if definition else TOOL_TIMEOUTS.get(name, 30)
    ok, data, error, latency_ms = False, None, None, 0
    try:
        if name in {"audio.voiceclone", "image.generate"}:
            ok, data, error, latency_ms = await asyncio.wait_for(
                asyncio.to_thread(_execute_short_tool_isolated, name, bound, user_id),
                timeout=timeout_sec,
            )
        else:
            ok, data, error, latency_ms = execute_short_tool(
                db, name, bound, user_id=user_id, allow_create=False
            )
    except TimeoutError:
        ok, data, error, latency_ms = False, None, f"工具执行超时（{timeout_sec}s）", timeout_sec * 1000
        agent_trace(f"ToolCall 超时 name={name} timeout={timeout_sec}s")
    except AppError as exc:
        ok, data, error, latency_ms = False, None, exc.message, 0
        agent_trace(f"ToolCall AppError name={name} code={exc.code.value} error={exc.message}")
    except Exception as exc:
        agent_exception(f"ToolCall 未捕获异常 name={name}", exc)
        ok, data, error, latency_ms = False, None, f"ToolCall 执行失败：{type(exc).__name__}", 0

    payload: dict[str, Any] = {"name": name, "ok": ok, "latency_ms": latency_ms}
    if ok:
        payload["data"] = data
        react.known_ids.extend(collect_ids(data))
        agent_trace(f"ToolCall 结束 name={name} ok=true latency={latency_ms}ms")
    else:
        payload["error"] = error or "该能力未启用"
        agent_trace(f"ToolCall 结束 name={name} ok=false latency={latency_ms}ms error={payload['error']}")
    await emit("tool_result", payload)
    react.observations.append(summarize_observation(name, ok, data, error, latency_ms))
    return ok


@dataclass
class McpStep:
    """模型本轮对 MCP 短工具的决策（不是 function calling）。"""

    thought: str
    tool: str | None
    arguments: dict[str, Any]
    done: bool
    reply: str
    latency_ms: int = 0
    reasoning_text: str = ""


def parse_mcp_step(raw: dict) -> McpStep:
    """把模型 JSON 收成合法 MCP 步骤。长工具名保留给循环移交，不在此丢弃。"""
    thought = str(raw.get("thought") or "").strip()
    reply = str(raw.get("reply") or "").strip()
    done = bool(raw.get("done"))
    tool_raw = raw.get("tool")
    tool: str | None
    if tool_raw in (None, "", "null", "none", "None"):
        tool = None
    else:
        tool = str(tool_raw).strip()
        if tool in WRITE_TOOLS:
            agent_trace(f"ReAct 丢弃写入工具 name={tool}")
            tool = None
            done = True
        elif is_long_tool(tool):
            # 保留名称供循环发移交思考卡；done 防止误入 execute
            done = True
        elif tool not in SHORT_TOOLS:
            agent_trace(f"ReAct 丢弃未知 MCP 工具 name={tool}")
            tool = None
            done = True
    arguments = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
    if not thought:
        if tool:
            thought = f"ToolCall「{TOOL_TITLES.get(tool, tool)}」"
        elif done:
            thought = "本轮观察已足够，停止调用工具"
    return McpStep(thought=thought, tool=tool, arguments=arguments, done=done or not tool, reply=reply)


def _call_mcp_step(db: Session, *, system: str, payload: dict, stop: threading.Event) -> McpStep:
    """同步调用模型，只要 JSON 决策，不走 function calling。"""
    from ..llm import call_agent_model_detailed

    if stop.is_set():
        raise RuntimeError("aborted")
    result = call_agent_model_detailed(
        db,
        system,
        json.dumps(payload, ensure_ascii=False),
        temperature=0,
        max_tokens=1024,
        timeout_s=MODEL_TIMEOUT_S,
    )
    parsed = parse_json_object(result.text)
    step = parse_mcp_step(parsed)
    step.latency_ms = result.latency_ms
    return step


async def _stream_mcp_step(
    *,
    system: str,
    payload: dict,
    stop: threading.Event,
    emit: EmitFn,
) -> McpStep:
    """流式跑一轮 MCP 决策：推理链走 thought.stream=think，正文只解析 JSON。"""
    from ..db import SessionLocal
    from ..llm import stream_agent_model

    loop = asyncio.get_running_loop()
    user_blob = json.dumps(payload, ensure_ascii=False)

    def _producer() -> tuple[str, str, int]:
        if stop.is_set():
            raise RuntimeError("aborted")
        tdb = SessionLocal()
        content_parts: list[str] = []
        thought_parts: list[str] = []
        started = time.perf_counter()
        try:
            for kind, chunk in stream_agent_model(
                tdb,
                system,
                user_blob,
                temperature=0,
                max_tokens=2048,
                timeout_s=90,
            ):
                if stop.is_set():
                    raise RuntimeError("aborted")
                if not chunk:
                    continue
                if kind == "reasoning":
                    thought_parts.append(chunk)
                    try:
                        asyncio.run_coroutine_threadsafe(
                            emit("thought", {"text": chunk, "stream": "think"}),
                            loop,
                        ).result(timeout=30)
                    except Exception:
                        pass
                else:
                    content_parts.append(chunk)
            latency_ms = round((time.perf_counter() - started) * 1000)
            return "".join(content_parts), "".join(thought_parts).strip()[:12000], latency_ms
        finally:
            tdb.close()

    content, reasoning, latency_ms = await asyncio.to_thread(_producer)
    if reasoning:
        await emit("thought", {"text": reasoning, "stream": "think_final"})
    try:
        parsed = parse_json_object(content)
    except ValueError:
        agent_trace("ReAct 流式 JSON 解析失败，回退非流式决策")
        isolated = SessionLocal()
        try:
            step = _call_mcp_step(isolated, system=system, payload=payload, stop=stop)
        finally:
            isolated.close()
        step.reasoning_text = reasoning
        if not step.latency_ms:
            step.latency_ms = latency_ms
        return step
    step = parse_mcp_step(parsed)
    step.latency_ms = latency_ms
    step.reasoning_text = reasoning
    return step


async def _emit_react_thought(
    emit: EmitFn,
    text: str,
    *,
    skill_id: str | None,
    latency_ms: int | None = None,
) -> None:
    """每轮一张思考卡：stage=react，技能徽标走 skill_id。"""
    payload: dict[str, Any] = {"text": text, "stage": "react"}
    if skill_id:
        payload["skill_id"] = skill_id
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    await emit("thought", payload)


async def _run_mcp_react_loop(
    db: Session,
    plan: PlanArtifact,
    react: ReactArtifact,
    *,
    user_id: str,
    emit: EmitFn,
    check_abort: AbortCheck,
    slash_fill_first: bool,
    text: str,
    attachments: list[str],
    stop: threading.Event,
    history: list[dict[str, str]],
    compact_summary: str | None,
    rounds_cap: int,
) -> None:
    """多轮 MCP ReAct：思考卡 → 一个短工具 → 观察 → 再思考，直到 done 或长任务移交。"""
    system = turn_system(
        react_system(),
        skill_id=plan.skill_id if plan.delivery == "confirm" else None,
        compact_summary=compact_summary,
    )
    executed_calls: dict[tuple[str, str], bool] = {}

    while react.rounds_used < rounds_cap:
        check_abort()
        payload = {
            "text": text,
            "intent": plan.intent,
            "skill_id": plan.skill_id,
            "delivery": plan.delivery,
            "slots": plan.slots,
            "history": history[-6:],
            "observations": list(react.observations),
            "round": react.rounds_used + 1,
            "max_rounds": rounds_cap,
            "attachments": attachments,
            "suggested_tools": list(plan.tools_needed),
            "note": "suggested_tools 只是规划建议，不是必须执行的清单",
        }
        try:
            step = await _stream_mcp_step(
                system=system,
                payload=payload,
                stop=stop,
                emit=emit,
            )
        except RuntimeError:
            check_abort()
            return
        except AppError as exc:
            agent_trace(f"ReAct 决策不可用 code={exc.code.value}，改走工具队列")
            return
        except Exception as exc:
            agent_exception("ReAct 决策内部异常，改走工具队列", exc)
            return

        react.used_llm = True
        if step.thought:
            react.thinking_text = (react.thinking_text + "\n" + step.thought).strip()[-12000:]
        if step.reasoning_text:
            react.thinking_text = (react.thinking_text + "\n" + step.reasoning_text).strip()[-12000:]
        elif step.thought:
            # 上游没有 reasoning_content 时，用 JSON thought 落一张可回放思考卡
            await _emit_react_thought(
                emit,
                step.thought,
                skill_id=plan.skill_id,
                latency_ms=step.latency_ms or None,
            )
        if step.reply:
            react.reply_text = step.reply

        raw_tool = _redirect_creative_tool(plan, text, step.tool)
        if raw_tool and is_long_tool(raw_tool):
            await _emit_react_thought(
                emit,
                f"「{raw_tool}」是长任务，确认后由 Worker 入队执行，对话进程不跑完。",
                skill_id=plan.skill_id,
            )
            break
        if not raw_tool or step.done:
            break

        args_key = json.dumps(step.arguments, ensure_ascii=False, sort_keys=True)
        dedup_key = (raw_tool, args_key)
        if dedup_key in executed_calls:
            agent_trace(f"跳过重复 MCP 调用 name={raw_tool}")
            await _emit_react_thought(
                emit,
                f"「{raw_tool}」相同参数已调用过，停止重复。",
                skill_id=plan.skill_id,
            )
            break

        react.rounds_used += 1
        ok = await _emit_and_run_tool(
            db,
            react,
            name=raw_tool,
            arguments=step.arguments,
            user_id=user_id,
            emit=emit,
            text=text,
            attachments=attachments,
        )
        executed_calls[dedup_key] = ok
        spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        react.proposed_spec = spec
        # 评测槽位已齐：结束 MCP 循环，把长任务交给确认卡 / Worker
        if plan.delivery == "confirm" and spec and not _missing_for_kind(spec):
            break


async def _run_tool_queue(
    db: Session,
    plan: PlanArtifact,
    react: ReactArtifact,
    *,
    queue: list[str],
    user_id: str,
    emit: EmitFn,
    check_abort: AbortCheck,
    slash_fill_first: bool,
    text: str,
    attachments: list[str],
    rounds_cap: int,
) -> None:
    """按规划队列串行执行尚未跑过的短工具（LLM 不可用或仍缺槽时的回退）。"""
    executed = set(_executed_names(react))
    pending = [name for name in queue if name and name not in executed]
    while pending and react.rounds_used < rounds_cap:
        check_abort()
        original = pending.pop(0)
        name = _redirect_creative_tool(plan, text, original)
        if not name:
            continue
        if name != original and name in executed:
            continue
        if is_long_tool(name):
            await _emit_react_thought(
                emit,
                f"「{name}」是长任务，确认后由 Worker 入队执行，对话进程不跑完。",
                skill_id=plan.skill_id,
            )
            break
        if name not in SHORT_TOOLS:
            agent_trace(f"跳过未知工具 name={name}")
            continue
        await _emit_react_thought(
            emit,
            f"ToolCall「{TOOL_TITLES.get(name, name)}」",
            skill_id=plan.skill_id,
        )
        react.rounds_used += 1
        ok = await _emit_and_run_tool(
            db,
            react,
            name=name,
            arguments={},
            user_id=user_id,
            emit=emit,
            text=text,
            attachments=attachments,
        )
        executed.add(name)
        if name == "task.create":
            continue
        spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        react.proposed_spec = spec
        if spec and not _missing_for_kind(spec):
            break
        if not ok:
            break
    if react.rounds_used >= rounds_cap and pending:
        agent_trace(f"工具轮次达到硬顶 rounds={react.rounds_used}")


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
) -> ReactArtifact:
    """ReAct 行动：优先 MCP JSON 多轮循环，失败则按 tools_needed 串行。

    ``prior`` + ``extra_tools`` 用于补规划后继续执行尚未跑过的工具，
    轮次计入同一 ``max_tool_rounds`` 硬顶（默认 4，硬顶 5）。
    ``use_llm=True`` 时走 Think-Act-Observe；单测默认 False 以免打上游。
    """
    react = prior or ReactArtifact()
    _ = PARALLEL_READONLY_TOOLS
    rounds_cap = min(int(plan.budget.get("max_tool_rounds") or DEFAULT_TOOL_ROUNDS), HARD_MAX_TOOL_ROUNDS)
    turn_attachments = list(attachments or [])

    if use_llm:
        await _run_mcp_react_loop(
            db,
            plan,
            react,
            user_id=user_id,
            emit=emit,
            check_abort=check_abort,
            slash_fill_first=slash_fill_first,
            text=text,
            attachments=turn_attachments,
            stop=stop or threading.Event(),
            history=list(history or []),
            compact_summary=compact_summary,
            rounds_cap=rounds_cap,
        )

    remaining = list(extra_tools) if extra_tools is not None else list(plan.tools_needed)
    if extra_tools is not None:
        # 补规划点名的尚未执行工具
        need_queue = bool(remaining)
    elif not react.used_llm:
        # 模型不可用：按规划清单串行，保证斜杠下单不空转
        need_queue = bool(remaining)
    elif slash_fill_first and plan.delivery == "confirm":
        spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        react.proposed_spec = spec
        need_queue = bool(remaining) and bool(spec and _missing_for_kind(spec))
    elif (
        plan.intent in {"benchmark", "rag", "testcase"}
        and plan.delivery == "confirm"
        and bool(remaining)
        and not _executed_names(react)
        and not (react.reply_text or "").strip()
    ):
        # 评测目标但模型一轮工具都没调：回退规划清单，避免空转澄清
        need_queue = True
    else:
        # 模型已自主决策（含 done=true 或部分工具后停止），不要再把清单当固定剧本跑完
        need_queue = False

    if need_queue:
        await _run_tool_queue(
            db,
            plan,
            react,
            queue=remaining,
            user_id=user_id,
            emit=emit,
            check_abort=check_abort,
            slash_fill_first=slash_fill_first,
            text=text,
            attachments=turn_attachments,
            rounds_cap=rounds_cap,
        )
    elif not remaining and not react.used_llm:
        react.proposed_spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        return react

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
