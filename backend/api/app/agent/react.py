"""ReAct 循环子图节点（M4 阶段 2，OR-2/OR-4）。

``react_agent_node`` 每轮：经 ``assemble`` 按 CX-4 装配上下文（Persona →
Skill Hint → 技能工作流 → 摘要 → 阶段输入 + observations）并用 ``select_tool_defs``
最小注入短原生工具（CX-5）→ 结构化模型调用 → ``parse_react`` 严格解析 → 写
``pending_tool``（工具路径）或完成后切换到自然语言流式回答（对话路径）。
``react_route`` 条件边按 ``pending_tool`` 分流；``tools_route`` 在预算耗尽时
END（避免撞 ``recursion_limit``）；预算在节点内消费（count-only，OR-5）；
重复调用/长路径抑制（OR-4）由「最近一次 tool 相同」检测并转 error 收尾。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from langgraph.config import get_config, get_stream_writer

from app.adapters import StreamAborted
from app.agent.log import agent_trace
from app.errors import AppError, ErrorCode
from app.harness.context import (
    assemble,
    compact_summary_from_configurable,
    select_tool_defs,
    skill_hints_for_turn,
    to_observation,
)
from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS, truncate_with_marker
from app.harness.contracts import Observation, TaskSessionState, evolve_task_state, make_event
from app.harness.execution import NativeToolResultStore, runtime_thread_id
from app.harness.execution.batch import build_tool_batch
from app.harness.execution.dispatch import READ_MAX_CHARS, resolve_read_offset
from app.harness.execution.stream_metrics import get_default_stream_metrics
from app.harness.execution.stream_policy import native_stream_allowed, profile_id_from_configurable
from app.harness.memory import GraphState, rebuild_model_config
from app.harness.orchestration import (
    DEFAULT_BUDGET,
    consume_model_call,
    consume_tool_turn,
    from_dict,
    is_budget_exhausted,
)
from app.harness.prompts import SystemVars, build_system_prompt, parse_react
from app.harness.skills import load_skill_workflow, plan_skill_id
from app.llm import ModelRequest, ModelResponse, NativeToolCall

# 阶段输入：ReAct 协议说明（M1 阶段输入，随节点注入，不做持久化）
REACT_STAGE_INPUT = """\
【当前阶段：ReAct 循环】
控制语义是 Observe → Think → Act：先阅读【工具结果】与修复建议，再思考，再决定
是否调用工具。禁止把工具原文当作最终回答。
只有收到平台返回的工具结果后才能声称该操作已成功；未调用工具或工具失败时，
必须如实说明，禁止口头编造执行结果或文件内容。
每轮输出严格 JSON（ReAct 协议 v1），禁止输出其他内容：
{"protocol": "react", "version": "react.v1", "thought": "简述本轮判断", "tool": "工具名或null", "arguments": {}, "done": false}
- 需要工具：tool 填工具名，arguments 填参数，done=false；
- 任务完成：tool=null，arguments={}，done=true。
- 读文件时 read 应省略 limit 一次读完，禁止人为拆成多个小页连续多次读取。
- 工具已返回内容即可基于内容直接作答；内容未读完也可直接 done=true 回答，不必强行读完。
- 禁止用完全相同参数重复调用已执行过的工具；如需继续，请换用不同命令，或直接 done=true 收尾。
可用工具（名称 + 参数要求）："""

# P2 默认优先走上游原生 ToolCall。工具 schema 由 ModelRequest.tools 透传，
# 不再要求支持 function calling 的模型把控制动作伪装为正文 JSON；旧协议 JSON
# 仍由下方兼容分支解析，便于逐个协议档迁移。
NATIVE_TOOL_STAGE_INPUT = """\
【当前阶段：原生工具调用】
控制语义是 Observe → Think → Act：先观察已返回的工具结果与修复建议，再思考，
再决定下一轮函数调用或给出自然语言结论。不要把工具原文粘贴成助手正文。
只有收到平台返回的工具结果后才能声称该操作已成功；未调用工具或工具失败时，
必须如实说明，禁止口头编造执行结果或文件内容。
如需访问平台工具，请使用模型协议提供的原生函数调用能力，并只从本轮提供的工具
schema 中选择。工具结果会以对应的 tool_call_id 返回；若系统同时给出【工具结果】，
也必须先阅读再作答，禁止在未看到返回内容时重复相同 read。
若模型无法发出原生函数调用，可改用 ReAct JSON（protocol=react.v1）；平台会执行
其中的 tool/arguments，并在下一轮把完整返回回填为 tool 消息与【工具结果】。
同一请求中的多个函数调用会由平台依次执行，每一个调用都经过权限门禁和沙箱。
读文件时 read 应省略 limit 参数一次读完（单次最多 2000 行），禁止人为拆成多个小页连续多次读取。
read 未读完时，把返回的 next_offset 填到下一次的 offset，禁止用相同 offset 重读。
"""


# 所有原生工具回传给模型的正文共用同一上限；超出只保留摘要并提示分页。
# ToolCard 另走行级受控预览，不走这条通道。

# 只读工具：相同参数成功一次后禁止再执行（OR-4）。read 必须换 offset 才能继续；
# web_search / web_fetch 用相同 query / url 重复调用不会得到新信息，同样拦截。
READONLY_TOOLS: frozenset[str] = frozenset({"read", "web_search", "web_fetch"})

# 只读工具「相同参数」成功调用的容忍上限：1 次即拦截重复读同一窗口。
READONLY_REPEAT_LIMIT = 1

# ReAct 协议解析失败纠正重试上限：模型输出非有效 JSON 时注入纠正观察并回环
# 一次（OR-4 同一回环边），仍失败才硬错误收尾；由模型调用预算兜底防死循环。
MAX_PARSE_RETRIES = 2

# 上下文注入最近观察条数上限：observations 已改为累积（OR-4 守卫需全量），
# 但注入系统提示只需最近若干条，避免长任务上下文无限膨胀（守卫仍看全量）。
# read 观察不受此条数限制（分页读取必须全页保留到最终回答阶段），但受下方总字符熔断。
INJECT_OBSERVATIONS_MAX = 6

# 注入的 read 观察总字符熔断：分页读超大文件时防止上下文被撑爆；
# 超预算时优先保留较新的页（尾部通常包含结论与续读线索）。
INJECT_READ_TOTAL_MAX_CHARS = 1_200_000

# 工具完成后的最终回答提示。ReAct 控制调用必须输出严格 JSON，不能直接把它的
# 增量投影到 assistant_delta；工具链收敛后单独做一次无工具自然语言流式调用。
FINAL_ANSWER_STAGE_INPUT = """\
【当前阶段：工具结果后的最终回答】
请基于用户问题和【工具结果】直接给出最终回答，使用自然语言，不要输出 JSON、
协议字段、工具调用或分析过程。若工具返回了内容，请准确引用或总结；若工具失败，
请如实说明并给出可行建议。不要逐字回显工具原文，应围绕用户问题提炼结论、依据和
下一步。回答可以分段，但不要添加与用户无关的说明。"""

# 只读工具重复调用达到上限后的附加约束。此时模型已经拥有同一份 Observation，
# 只能根据它收敛回答，不能把 Observation 伪装成助手正文或继续请求工具。
FORCED_FINAL_ANSWER_INPUT = """\
【系统收敛约束】
同一只读工具已使用相同参数重复执行，系统不会再执行该调用。请只根据已有工具结果
完成回答；不得再次请求工具，也不得逐字粘贴工具原文。"""

FINAL_ANSWER_EMPTY_TEXT = "工具已执行，但未生成可展示的最终回答。"

# P1 阶段叙述字数上限（API.md V1.33）；超出截断，禁止写入 Observation 原文。
NARRATION_MAX_CHARS = 200


@dataclass(frozen=True, slots=True)
class _NativeRoundTrace:
    """单次模型回合的脱敏计时；成功/失败只允许记一笔终态。"""

    first_delta_ms: int | None = None
    tool_call_parse_ms: int | None = None
    invoke_fallback: bool = False


def _record_native_round(
    trace: _NativeRoundTrace,
    *,
    associate_error: bool = False,
    upstream: bool = False,
    incomplete: bool = False,
) -> None:
    """每个模型回合只记一笔，避免成功流把关联错乱的脚踢计数清零。"""
    get_default_stream_metrics().record_stream(
        first_delta_ms=trace.first_delta_ms,
        tool_call_parse_ms=trace.tool_call_parse_ms,
        invoke_fallback=trace.invoke_fallback,
        associate_error=associate_error,
        upstream=upstream,
        incomplete=incomplete,
    )


def _stage_narration(text: str) -> str:
    """把模型旁白压成阶段叙述，不含工具原文。"""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) > NARRATION_MAX_CHARS:
        return cleaned[:NARRATION_MAX_CHARS] + "…"
    return cleaned


def _tool_call_event(call: Mapping[str, object]) -> dict:
    """在 ToolNode 执行前持久化 ToolCall，保证瞬态输出可关联到现有卡片。"""
    return make_event(
        "tool_call",
        {
            "call_id": str(call.get("call_id") or ""),
            "name": str(call.get("name") or ""),
            "arguments": dict(call.get("arguments") or {}),
        },
    )


logger = logging.getLogger("ai-eval.agent-react")


def _normalized_tool_arguments(name: str, arguments: Mapping[str, object] | None) -> dict[str, object]:
    """归一化工具参数，避免 offset/next_offset 别名导致重复读无法识别。"""
    raw = dict(arguments or {})
    if name != "read":
        return raw
    offset = resolve_read_offset(raw)
    try:
        normalized_offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        normalized_offset = 0
    normalized: dict[str, object] = {"path": str(raw.get("path") or ""), "offset": normalized_offset}
    if raw.get("limit") is not None:
        try:
            normalized["limit"] = int(raw["limit"])
        except (TypeError, ValueError):
            pass
    return normalized


def _readonly_call_key(name: str, arguments: Mapping[str, object] | None) -> tuple[object, ...]:
    """只读调用指纹：工具名 + 归一化参数，供历史比对与同批去重。"""
    return (name, tuple(sorted(_normalized_tool_arguments(name, arguments).items())))


def _identical_success_count(
    state: GraphState,
    name: str,
    arguments: Mapping[str, object] | None,
    *,
    limit: int | None = None,
) -> int:
    """统计相同参数且成功的历史调用次数；``limit`` 到达即短路（OR-4）。"""
    wanted = _normalized_tool_arguments(name, arguments)
    count = 0
    for observation in state.get("observations") or []:
        if getattr(observation, "tool", None) != name:
            continue
        if not getattr(observation, "ok", False):
            continue
        if _normalized_tool_arguments(name, getattr(observation, "arguments", None)) != wanted:
            continue
        count += 1
        if limit is not None and count >= limit:
            return count
    return count


def _repeat_correction_observation(tool: str, arguments: Mapping[str, object], runs: int) -> Observation:
    """只读工具重复调用的纠正观察，不执行工具。"""
    return Observation(
        tool=tool,
        text=(
            f"系统提示：工具 {tool} 已用相同参数成功执行 {runs} 次，"
            "返回内容完全相同，继续相同调用不会得到新信息。"
            "如需读取未读部分：请把上次的 next_offset 填到 offset 再读；"
            "如已读内容足够：请直接用自然语言作答，不要再用相同参数调用。"
        ),
        ok=False,
        redacted=True,
        arguments=dict(arguments),
    )


def _cached_replay_text(state: GraphState, name: str, arguments: Mapping[str, object]) -> str | None:
    """取最近一次相同参数成功调用的结果正文，供重复调用缓存回放。"""
    wanted = _normalized_tool_arguments(name, arguments)
    for observation in reversed(state.get("observations") or []):
        if getattr(observation, "tool", None) != name:
            continue
        if not getattr(observation, "ok", False):
            continue
        if _normalized_tool_arguments(name, getattr(observation, "arguments", None)) != wanted:
            continue
        text = str(getattr(observation, "text", "") or "")
        if text:
            return text
    return None


def _cached_native_replay_text(
    state: GraphState,
    store: NativeToolResultStore | None,
    thread_id: str,
    name: str,
    arguments: Mapping[str, object] | None,
) -> str | None:
    """native 路径的缓存回放正文：观察里只留摘要，正文在本回合结果存储。

    沿 ``native_messages`` 回溯相同参数的 assistant tool_call，再按 call_id
    从单回合 store 取回完整正文；存储不可用或已失效时返回 None。
    """
    if store is None:
        return None
    wanted = _normalized_tool_arguments(name, arguments)
    for raw in reversed(state.get("native_messages") or ()):
        if str(raw.get("role") or "") != "assistant":
            continue
        for call in raw.get("tool_calls") or ():
            if not isinstance(call, Mapping):
                continue
            if str(call.get("name") or "") != name:
                continue
            if _normalized_tool_arguments(name, call.get("arguments")) != wanted:
                continue
            text = store.get(thread_id, str(call.get("call_id") or ""))
            if text:
                return text
    return None


def _repeat_replay_observation(
    tool: str, arguments: Mapping[str, object], cached_text: str, runs: int
) -> Observation:
    """只读工具重复调用的缓存回放观察（legacy 注入路径）。"""
    return Observation(
        tool=tool,
        text=(
            f"(系统提示：本次调用与第 {runs} 次成功执行参数相同，"
            "以下为缓存回放，内容与上次完全一致；如需新内容请换参数，"
            "否则请直接基于该内容作答。)\n" + cached_text
        ),
        ok=True,
        arguments=dict(arguments),
    )


def _split_native_readonly_repeats(
    state: GraphState, calls: tuple[NativeToolCall, ...]
) -> tuple[tuple[NativeToolCall, ...], NativeToolCall | None, int]:
    """拆出可执行的原生调用与被 OR-4 拦截的只读重复调用。

    同时拦截「历史已成功」与「同一响应内相同指纹」两类重复，避免同批
    多个相同 read 在 ToolNode 串行执行时绕过守卫。
    """
    allowed: list[NativeToolCall] = []
    skipped: NativeToolCall | None = None
    skipped_runs = 0
    seen: set[tuple[object, ...]] = set()
    for call in calls:
        if call.name in READONLY_TOOLS:
            key = _readonly_call_key(call.name, call.arguments)
            runs = _identical_success_count(
                state, call.name, call.arguments, limit=READONLY_REPEAT_LIMIT
            )
            if key in seen or runs >= READONLY_REPEAT_LIMIT:
                skipped = call
                skipped_runs = max(runs, 1)
                continue
            seen.add(key)
        allowed.append(call)
    return tuple(allowed), skipped, skipped_runs


def _forced_repeat_completion(
    *,
    state: GraphState,
    gateway: object,
    request: ModelRequest,
    model_run_config: dict,
    system: str,
    budget: object,
    started: float,
    pending_events: list,
    close_turn: bool,
    response: ModelResponse,
) -> dict:
    """只读重复纠正无效后，走无工具最终回答，不回显 Observation 原文。"""
    budget = consume_model_call(budget)
    final_response = _generate_final_answer(
        gateway,
        request,
        model_run_config,
        system=system,
        extra_instruction=FORCED_FINAL_ANSWER_INPUT,
    )
    text = (
        final_response.text
        if final_response is not None and final_response.text.strip()
        else FINAL_ANSWER_EMPTY_TEXT
    )
    forced_usage = (
        dict(final_response.usage)
        if final_response is not None
        else dict(response.usage)
    )
    finished = _assistant_completion(
        text,
        usage=forced_usage,
        latency_ms=round((time.perf_counter() - started) * 1000),
        pending_events=pending_events,
        close_turn=close_turn,
        turn_stats=_turn_stats(state, budget, forced_usage),
    )
    finished["budget"] = budget.to_dict()
    return finished


def _inject_observations(state: GraphState) -> str:
    """把 observations 归一为摘要文本（M2 to_observation，脱敏在注入前）。

    非 read 观察只注入最近 ``INJECT_OBSERVATIONS_MAX`` 条；read 观察不受条数
    上限：分页读取的每一页都必须保留到最终回答阶段，否则模型只能基于尾部页
    作答导致内容不全。read 总字符受 ``INJECT_READ_TOTAL_MAX_CHARS`` 熔断，
    超出时优先保留较新的页。守卫（identical_runs）仍消费全量累积观察。
    """
    all_observations = list(state.get("observations") or ())
    if not all_observations:
        return ""
    recent_non_read_ids = {
        id(item)
        for item in [
            observation
            for observation in all_observations
            if str(getattr(observation, "tool", "") or "") != "read"
        ][-INJECT_OBSERVATIONS_MAX:]
    }
    # read 页倒序准入预算，确保超熔断时丢的是最早的页。
    read_budget = INJECT_READ_TOTAL_MAX_CHARS
    read_kept_ids: set[int] = set()
    for observation in reversed(all_observations):
        if str(getattr(observation, "tool", "") or "") != "read":
            continue
        cost = min(len(str(getattr(observation, "text", "") or "")), READ_MAX_CHARS)
        if read_budget - cost < 0 and read_kept_ids:
            break
        read_budget -= cost
        read_kept_ids.add(id(observation))
    selected = [
        observation
        for observation in all_observations
        if id(observation) in read_kept_ids or id(observation) in recent_non_read_ids
    ]
    if not selected:
        return ""
    lines = [
        # read 的正文可达 READ_MAX_CHARS（1000 行量级一次读完），其余工具
        # 仍用全局 8000 字符预算，避免 bash/web 输出挤占上下文。
        to_observation(
            observation,
            max_chars=READ_MAX_CHARS if observation.tool == "read" else MODEL_TOOL_RESULT_MAX_CHARS,
        )
        for observation in selected
    ]
    return "【工具结果】\n" + "\n".join(lines)


def _extract_thought(raw: str) -> str:
    """从模型输出中提取 thought 回显（PR-3：只回显不触发动作）。

    ``parse_react`` 的 fields 不含 thought（授权字段），done 收尾需要回显
    给用户；此处容错提取，失败返回空串。
    """
    import json

    try:
        data = json.loads(raw.strip())
        text = data.get("thought")
        return str(text) if text else ""
    except (json.JSONDecodeError, AttributeError):
        return ""


def _looks_like_legacy_react(raw: str) -> bool:
    """仅在模型明显输出旧 ReAct 控制 JSON 时进入兼容解析与纠正流程。"""
    text = raw.lstrip()
    return text.startswith("{") and '"protocol"' in text[:300] and "react" in text[:300]


def _json_react_tool_payload(
    *,
    native_tool_mode: bool,
    call_id: str,
    tool: str,
    arguments: dict,
    thought_events: list[dict],
    budget: object,
    thought_text: str = "",
) -> dict:
    """把 JSON ReAct 的 tool/arguments 排进 ToolNode。

    native 协议档下必须标 ``native=True`` 并写入 ToolBatch / assistant ToolCall
    消息，下一轮才能按 call_id 水合完整 Observation；否则模型只会看到空的
    role=tool 通道，误以为 read 没有返回。
    """
    pending_call = {
        "call_id": call_id,
        "name": tool,
        "arguments": arguments,
        "native": native_tool_mode,
    }
    payload: dict = {
        "pending_tool": pending_call,
        "pending_tools": [],
        "pending_events": [*thought_events, _tool_call_event(pending_call)],
        "repeat_retry": False,
        "budget": budget.to_dict() if hasattr(budget, "to_dict") else budget,
    }
    if native_tool_mode:
        native_call = NativeToolCall(call_id, tool, arguments)
        payload["pending_tool_batch"] = build_tool_batch([pending_call])
        payload["native_messages"] = [_native_tool_message((native_call,), thought_text)]
    return payload


def _native_tool_message(tool_calls: tuple[NativeToolCall, ...], text: str) -> dict[str, object]:
    """构造协议无关 assistant ToolCall 消息，下一轮由适配器映射到上游格式。"""
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "call_id": call.call_id,
                "name": call.name,
                "arguments": dict(call.arguments),
            }
            for call in tool_calls
        ],
    }


def _hydrate_native_messages(
    state: GraphState,
    native_tool_results: NativeToolResultStore | None,
    thread_id: str,
) -> tuple[dict[str, object], ...]:
    """用单回合临时缓存补齐 ToolResult 正文，避免原文写入检查点。

    检查点中的 ``native_messages`` 只保留 ToolCall/ToolResult 的关联元数据；若
    进程在回合中断后无法恢复临时内容，明确告知模型结果不可用，禁止编造结论。
    """
    hydrated: list[dict[str, object]] = []
    # call_id → 工具名兜底映射（部分消息的 name 字段可能缺失）：
    # read 的 ToolResult 正文可达 READ_MAX_CHARS，其余工具维持全局 8000 裁剪。
    tool_names: dict[str, str] = {}
    for raw in state.get("native_messages") or ():
        if str(raw.get("role") or "") != "assistant":
            continue
        for call in raw.get("tool_calls") or ():
            if isinstance(call, Mapping):
                call_id = str(call.get("call_id") or "")
                name = str(call.get("name") or "")
                if call_id and name:
                    tool_names[call_id] = name
    for raw in state.get("native_messages") or ():
        message = dict(raw)
        if str(message.get("role") or "") == "tool":
            call_id = str(message.get("tool_call_id") or "")
            tool_name = str(message.get("name") or "") or tool_names.get(call_id, "")
            content = (
                native_tool_results.get(thread_id, call_id)
                if native_tool_results is not None
                else None
            )
            if content is None:
                message["content"] = "工具结果在当前会话中不可用，请向用户说明并请求重试。"
            else:
                budget = (
                    READ_MAX_CHARS
                    if tool_name == "read"
                    else MODEL_TOOL_RESULT_MAX_CHARS
                )
                clipped, truncated = truncate_with_marker(content, budget)
                if truncated:
                    clipped += " 请用更小范围继续调用（如 read 传 next_offset），不要重复相同参数。"
                message["content"] = clipped
        hydrated.append(message)
    return tuple(hydrated)


def _model_gateway_config(run_config: object) -> dict[str, object]:
    """仅向模型调用子图传递取消回调，隔离会话凭据与工具原文。"""
    configurable = (run_config or {}).get("configurable") if isinstance(run_config, dict) else None
    abort = configurable.get("abort") if isinstance(configurable, Mapping) else None
    return {"configurable": {"abort": dict(abort)}} if isinstance(abort, Mapping) else {"configurable": {}}


def _validated_native_tool_calls(
    tool_calls: tuple[NativeToolCall, ...],
) -> tuple[NativeToolCall, ...]:
    """校验上游 ToolCall 的关联契约，禁止空或重复 ID 进入工具队列。"""
    seen_ids: set[str] = set()
    normalized: list[NativeToolCall] = []
    for call in tool_calls:
        call_id = str(call.call_id or "").strip()
        name = str(call.name or "").strip()
        if not call_id:
            raise AppError(ErrorCode.UPSTREAM, "上游工具调用缺少 call_id")
        if call_id in seen_ids:
            raise AppError(ErrorCode.UPSTREAM, "上游工具调用存在重复 call_id")
        if not name:
            raise AppError(ErrorCode.UPSTREAM, "上游工具调用缺少工具名")
        if not isinstance(call.arguments, Mapping):
            raise AppError(ErrorCode.UPSTREAM, "上游工具调用参数无效")
        seen_ids.add(call_id)
        normalized.append(
            NativeToolCall(call_id=call_id, name=name, arguments=dict(call.arguments))
        )
    return tuple(normalized)


def _has_active_plan(state: GraphState) -> bool:
    """当前回合是否带规划产物（有 plan 时由 reflect 统一发 completed）。"""
    return isinstance(state.get("plan"), dict)


# 工具指令守卫：用户消息必须同时命中"动作词 + 工具名"才视为明确要求调用工具，
# 避免"解释一下什么是 bash"这类提及场景误伤。
_TOOL_ACTION_WORDS = frozenset(
    {"工具", "调用", "使用", "运行", "执行", "读取", "写入", "编辑", "查看", "帮我"}
)
_USER_TOOL_NAMES = frozenset({"read", "write", "edit", "bash", "web_search", "web_fetch"})
# 守卫纠正观察的哨兵工具名：不计入 _has_tool_observation（防放行幻觉收尾）。
GUARD_TOOL = "__guard__"


def _requested_tool_correction(state: GraphState) -> Observation | None:
    """工具指令守卫：用户明确要求调用工具但本回合尚未调用任何工具。

    反幻觉（生产实测）：qwen3.6-flash 对"用 write 修改文件"直接输出
    done=true 的 ReAct JSON，thought 声称"已成功更新"，实际 0 次工具调用。
    模型尝试收尾时注入纠正观察强制其先调用工具；已有工具结果则放行。
    """
    if _has_tool_observation(state):
        return None
    raw = state.get("request") or {}
    messages = raw.get("messages") if isinstance(raw, Mapping) else None
    if not messages:
        return None
    last = messages[-1] if isinstance(messages, list | tuple) and messages else None
    text = str((last or {}).get("content") or "").lower()
    if not any(word in text for word in _TOOL_ACTION_WORDS):
        return None
    for name in _USER_TOOL_NAMES:
        if name in text:
            # tool 用专用哨兵名 "__guard__"：既不触发 _has_tool_observation（防
            # 误判为真实工具执行后放行幻觉收尾），也不进入 __parse__ 排除逻辑。
            return Observation(
                tool=GUARD_TOOL,
                text=(
                    f"系统提示：用户明确要求调用 {name} 工具，但你尚未调用任何工具。"
                    "禁止口头声称操作已执行；必须先实际调用工具拿到真实结果，"
                    "再基于工具结果回答。"
                ),
                ok=False,
                redacted=True,
            )
    return None


def _plan_tools_needed(state: GraphState) -> tuple[str, ...]:
    """从 PlanArtifact 投影取出本轮点名的短工具名（未注册项由 select_tool_defs 丢弃）。"""
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return ()
    raw = plan.get("tools_needed") or ()
    return tuple(str(item) for item in raw if str(item).strip())


def _format_task_state_input(task_state_data: Mapping[str, object]) -> str:
    """把 TaskSessionState 格式化为置顶的任务状态黑板提示词。"""
    try:
        ts = TaskSessionState.from_dict(task_state_data)
    except Exception:
        return ""

    parts = ["【当前规划】\n【结构化任务看板 (Session Task State)】"]
    if ts.goal:
        parts.append(f"🎯 终局目标：{ts.goal}")
    parts.append(f"🚦 当前阶段：{ts.phase}")
    if ts.current_hypothesis:
        parts.append(f"💡 当前验证假设：{ts.current_hypothesis}")

    if ts.confirmed_facts:
        fact_lines = "\n".join(f"  - {fact}" for fact in ts.confirmed_facts[:5])
        parts.append(f"🔍 已确立事实 ({len(ts.confirmed_facts)}项)：\n{fact_lines}")

    if ts.evidence:
        ev_lines = "\n".join(f"  - {item}" for item in ts.evidence[:5])
        parts.append(f"📌 关键技术证据 ({len(ts.evidence)}条)：\n{ev_lines}")

    if ts.rejected_hypotheses:
        rej_lines = "\n".join(
            f"  - {item.hypothesis}（原因：{item.reason}）"
            for item in ts.rejected_hypotheses[:3]
        )
        parts.append(f"❌ 已排除/证伪方向 ({len(ts.rejected_hypotheses)}项，切勿重复踩坑)：\n{rej_lines}")

    if ts.failed_steps:
        fail_lines = "\n".join(
            f"  - {item.step}（原因：{item.reason}）"
            for item in ts.failed_steps[:3]
        )
        parts.append(f"⚠️ 曾失败步骤 ({len(ts.failed_steps)}项)：\n{fail_lines}")

    if ts.missing_info:
        missing_lines = "\n".join(f"  - {info}" for info in ts.missing_info[:5])
        parts.append(f"⏳ 关键信息缺口 (Missing Info，严禁收尾！)：\n{missing_lines}")

    if ts.current_step:
        parts.append(f"📋 当前推进步骤：{ts.current_step}")
    if ts.next_actions:
        action_lines = "\n".join(f"  {idx}. {act}" for idx, act in enumerate(ts.next_actions[:3], start=1))
        parts.append(f"⏭️ 紧随动作建议：\n{action_lines}")

    parts.append(
        "【交付与收尾门禁】：\n"
        f"当前 can_deliver={ts.can_deliver}。"
        + (
            "关键信息缺口尚未闭环，严禁直接以最终结论形式交付回答！必须优先调用工具探查缺失项。"
            if ts.missing_info or not ts.can_deliver
            else "关键证据已完备，可组织最终交付结论。"
        )
    )
    return "\n".join(parts)


def _plan_stage_input(state: GraphState) -> str:
    """把 TaskSessionState 或 PlanArtifact 投影成模型可见的规划与状态约束。"""
    task_state_data = state.get("task_state")
    if isinstance(task_state_data, Mapping):
        formatted = _format_task_state_input(task_state_data)
        if formatted:
            return formatted

    plan = state.get("plan")
    if not isinstance(plan, dict):
        return ""
    slots = plan.get("slots") if isinstance(plan.get("slots"), dict) else {}
    if isinstance(slots.get("task_state"), Mapping):
        formatted = _format_task_state_input(slots["task_state"])
        if formatted:
            return formatted

    steps = slots.get("steps") if isinstance(slots, dict) else None
    step_lines = ""
    if isinstance(steps, list) and steps:
        step_lines = "\n".join(f"{index}. {item}" for index, item in enumerate(steps, start=1))
    tools = "、".join(str(item) for item in (plan.get("tools_needed") or ())) or "task"
    return (
        "【当前规划】\n"
        f"意图：{plan.get('intent') or ''}\n"
        f"交付：{plan.get('delivery') or 'chat'}\n"
        f"短工具：{tools}\n"
        "请先观察已有工具结果，再按步骤行动；长任务（评测/用例/压测/知识库）"
        "不得在对话内同步执行，应说明需经确认卡入队。\n"
        f"{step_lines}"
    ).strip()


def _react_error_state(
    state: GraphState,
    *,
    code: str,
    message: str,
    extra_events: list[dict] | None = None,
    **updates: object,
) -> dict[str, object]:
    """硬错误收尾：有 plan 时自带 completed(error)，并禁止再进 reflect。"""
    events = list(extra_events or [])
    events.append(make_event("error", {"code": code, "message": message}))
    if _has_active_plan(state):
        events.append(
            make_event(
                "response.completed",
                {"finish_reason": "error", "role": "assistant"},
            )
        )
    result: dict[str, object] = {
        "pending_events": events,
        "pending_tool": None,
        "pending_tools": [],
        "pending_tool_batch": None,
        "repeat_retry": False,
        "turn_failed": True,
    }
    result.update(updates)
    return result


def _turn_stats(
    state: GraphState,
    budget: object,
    usage: dict[str, int] | object,
) -> dict[str, object]:
    """turn 级观测指标：模型轮数 / token 用量 / 工具成败计数。

    随 ``assistant_message`` 事件广播并落库（messages.turn_stats），供前端
    与运维做性能归因；禁止包含正文、参数等敏感内容。
    """
    observations = [
        item
        for item in (state.get("observations") or [])
        if getattr(item, "tool", "") != "__parse__"
    ]
    tool_total = len(observations)
    tool_failures = sum(1 for item in observations if not getattr(item, "ok", False))
    usage_dict = dict(usage) if isinstance(usage, dict) else {}
    budget_dict = budget.to_dict() if hasattr(budget, "to_dict") else {}
    model_calls_used = max(
        0, DEFAULT_BUDGET["model_calls"] - int(budget_dict.get("model_calls", DEFAULT_BUDGET["model_calls"]))
    )
    return {
        "model_calls": model_calls_used,
        "tool_calls": tool_total,
        "tool_failures": tool_failures,
        "prompt_tokens": usage_dict.get("prompt_tokens"),
        "completion_tokens": usage_dict.get("completion_tokens"),
        "total_tokens": usage_dict.get("total_tokens"),
    }


def _assistant_completion(
    text: str,
    *,
    usage: dict[str, int] | object,
    latency_ms: int,
    pending_events: list[dict] | None = None,
    close_turn: bool = True,
    turn_stats: dict[str, object] | None = None,
) -> dict[str, object]:
    """统一构造自然语言收尾投影，避免原生/兼容路径产生不同事件契约。"""
    events = list(pending_events or [])
    message_payload: dict[str, object] = {"text": text, "role": "assistant", "latency_ms": latency_ms}
    if turn_stats is not None:
        message_payload["turn_stats"] = turn_stats
    events.append(
        make_event(
            "assistant_message",
            message_payload,
        )
    )
    if close_turn:
        events.append(
            make_event(
                "response.completed",
                {"finish_reason": "stop", "role": "assistant"},
            )
        )
    return {
        "pending_events": events,
        "response": {"text": text, "usage": dict(usage or {}), "latency_ms": latency_ms},
        "pending_tool": None,
        "pending_tools": [],
        "pending_tool_batch": None,
        "repeat_retry": False,
    }


def _has_tool_observation(state: GraphState) -> bool:
    """判断当前 ReAct 回合是否已经执行过真实工具。

    ``__parse__``（协议解析纠正）与 ``__guard__``（工具指令守卫纠正）都不是
    真实工具执行，不计入。
    """
    return any(
        str(getattr(observation, "tool", "") or "") not in ("", "__parse__", GUARD_TOOL)
        for observation in (state.get("observations") or [])
    )


def _final_answer_request(
    request: ModelRequest,
    *,
    system: str,
    extra_instruction: str = "",
) -> ModelRequest:
    """构造无工具的最终回答请求，避免 ReAct 控制 JSON 混入助手正文。"""
    instructions = FINAL_ANSWER_STAGE_INPUT
    if extra_instruction:
        instructions += "\n\n" + extra_instruction
    return ModelRequest(
        config=request.config,
        messages=request.messages,
        system=system + "\n\n" + instructions,
        tools=(),
    )


def _stream_final_answer(
    gateway: object,
    answer_request: ModelRequest,
    run_config: dict,
) -> ModelResponse | None:
    """流式生成工具链收敛后的自然语言回答并投影正文增量。

    ReAct 控制调用的输出是协议 JSON，不能直接作为助手正文流出。工具调用完成
    后改用无工具提示再次调用模型，复用 ``ModelGateway.stream`` 的正文/思考增量，
    由外层 WebSocket 投影为 ``assistant_delta`` / ``thought``。
    """
    stream = getattr(gateway, "stream", None)
    if not callable(stream):
        return None

    writer = get_stream_writer()
    content: list[str] = []
    final_response: ModelResponse | None = None
    started = time.perf_counter()
    try:
        for event in stream(answer_request, config=run_config):
            if event.kind == "completed":
                final_response = event.response
                continue
            if not event.text:
                continue
            if event.kind == "reasoning":
                writer({"kind": "reasoning", "text": event.text})
            elif event.kind == "content":
                content.append(event.text)
                writer({"kind": "content", "text": event.text})
    except StreamAborted:
        raise
    except AppError:
        raise
    except Exception as exc:
        logger.info("ReAct 最终回答流式调用异常 type=%s", type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "最终回答生成失败") from exc

    if final_response is None:
        final_response = ModelResponse(
            text="".join(content),
            usage={},
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    elif not final_response.text and content:
        # 兼容测试网关或上游未携带收尾正文的情况，避免最终事件覆盖已流出的内容。
        final_response = ModelResponse(
            text="".join(content),
            usage=final_response.usage,
            raw=final_response.raw,
            latency_ms=final_response.latency_ms,
        )
    return final_response


def _stream_native_tool_round(
    gateway: object,
    request: ModelRequest,
    run_config: dict,
) -> tuple[ModelResponse, _NativeRoundTrace] | None:
    """流式执行原生工具回合（含首轮），投影正文增量，响应结束后才交出 ToolCall。

    工具参数碎片不投影到外层；完整 ``tool_call`` 事件只用于拼回收尾响应，
    由调用方在上游响应结束后再写入 ``pending_tool(s)`` 并落卡。
    成功路径不记账，由调用方在 call_id 校验后再记终态。
    """
    stream = getattr(gateway, "stream", None)
    if not callable(stream):
        return None

    writer = get_stream_writer()
    content: list[str] = []
    collected_calls: list[NativeToolCall] = []
    final_response: ModelResponse | None = None
    started = time.perf_counter()
    first_delta_ms: int | None = None
    tool_call_parse_ms: int | None = None
    hold_possible_json = False
    metrics = get_default_stream_metrics()
    try:
        for event in stream(request, config=run_config):
            if event.kind == "completed":
                final_response = event.response
                continue
            if event.kind == "tool_call":
                # 上游工具参数只在网关确认完整后返回；实际 ToolCard 仍由
                # 响应结束后的 pending_events 投影，避免半截参数出站。
                if event.tool_call is not None:
                    if tool_call_parse_ms is None:
                        tool_call_parse_ms = round((time.perf_counter() - started) * 1000)
                    collected_calls.append(event.tool_call)
                continue
            if not event.text:
                continue
            if event.kind == "reasoning":
                writer({"kind": "reasoning", "text": event.text})
            elif event.kind == "content":
                if first_delta_ms is None:
                    first_delta_ms = round((time.perf_counter() - started) * 1000)
                content.append(event.text)
                preview = "".join(content).lstrip()
                # ReAct 控制 JSON 不能当助手正文下发；先暂扣以 ``{`` 开头的增量，
                # 收尾后若确认是 protocol=react 则丢弃投影，改由 thought/ToolCard 承接。
                if preview.startswith("{") and not collected_calls:
                    hold_possible_json = True
                    continue
                if not hold_possible_json:
                    writer({"kind": "content", "text": event.text})
    except StreamAborted:
        metrics.record_stream(
            first_delta_ms=first_delta_ms,
            tool_call_parse_ms=tool_call_parse_ms,
            cancelled=True,
        )
        raise
    except AppError as exc:
        metrics.record_stream(
            first_delta_ms=first_delta_ms,
            tool_call_parse_ms=tool_call_parse_ms,
            incomplete=exc.code in {ErrorCode.UPSTREAM, ErrorCode.TIMEOUT},
            upstream=exc.code == ErrorCode.UPSTREAM,
        )
        raise
    except Exception as exc:
        logger.info("ReAct 原生工具回合流式调用异常 type=%s", type(exc).__name__)
        metrics.record_stream(
            first_delta_ms=first_delta_ms,
            tool_call_parse_ms=tool_call_parse_ms,
            incomplete=True,
        )
        raise AppError(ErrorCode.INTERNAL, "原生工具回合生成失败") from exc

    agent_trace(
        f"native_stream first_delta_ms={first_delta_ms} "
        f"tool_call_parse_ms={tool_call_parse_ms} tools={len(collected_calls)}"
    )
    trace = _NativeRoundTrace(
        first_delta_ms=first_delta_ms,
        tool_call_parse_ms=tool_call_parse_ms,
    )

    merged_text = "".join(content)
    merged_calls = tuple(collected_calls)
    if hold_possible_json and merged_text and not _looks_like_legacy_react(merged_text):
        writer({"kind": "content", "text": merged_text})
    if final_response is None:
        return (
            ModelResponse(
                text=merged_text,
                usage={},
                latency_ms=round((time.perf_counter() - started) * 1000),
                tool_calls=merged_calls,
            ),
            trace,
        )
    text = final_response.text or merged_text
    tool_calls = final_response.tool_calls or merged_calls
    if text == final_response.text and tool_calls == final_response.tool_calls:
        return final_response, trace
    return (
        ModelResponse(
            text=text,
            usage=final_response.usage,
            raw=final_response.raw,
            latency_ms=final_response.latency_ms,
            tool_calls=tool_calls,
        ),
        trace,
    )


def _generate_final_answer(
    gateway: object,
    request: ModelRequest,
    run_config: dict,
    *,
    system: str,
    extra_instruction: str = "",
) -> ModelResponse | None:
    """生成工具链收敛后的最终正文，优先流式，缺失流式能力时仍调用模型。

    测试夹具或极少数私有网关可能只有 ``invoke``。此时必须继续发起一轮无工具的
    自然语言调用，不能退回 ReAct ``thought``，更不能直接发送 Observation 原文。
    """
    answer_request = _final_answer_request(
        request,
        system=system,
        extra_instruction=extra_instruction,
    )
    stream = getattr(gateway, "stream", None)
    if callable(stream):
        return _stream_final_answer(gateway, answer_request, run_config)

    invoke = getattr(gateway, "invoke", None)
    if not callable(invoke):
        return None
    try:
        response = invoke(answer_request, config=run_config)
    except AppError:
        raise
    except Exception as exc:
        logger.info("ReAct 最终回答调用异常 type=%s", type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "最终回答生成失败") from exc
    if not isinstance(response, ModelResponse):
        raise AppError(ErrorCode.INTERNAL, "最终回答未产生有效响应")
    return response


def build_react_nodes(
    gateway: object,
    registry: object,
    *,
    native_tool_results: NativeToolResultStore | None = None,
) -> dict[str, Callable]:
    """构造 ReAct 节点：{'react_agent': ...}；条件边路由见 ``react_route``。"""

    def react_agent_node(state: GraphState) -> dict:
        # 工具回边若漏判耗尽，这里再挡一次：不再调模型，直接 error 收尾。
        budget = from_dict(state.get("budget") or {})
        if is_budget_exhausted(budget):
            message = (
                "模型调用次数预算耗尽"
                if budget.model_calls <= 0
                else "工具轮次预算耗尽"
            )
            return _react_error_state(
                state,
                code=ErrorCode.BUDGET_EXCEEDED.value,
                message=message,
                budget=budget.to_dict(),
            )
        serializable = state["request"]
        run_config = get_config()
        configurable = (run_config or {}).get("configurable") or {}
        thread_id = runtime_thread_id(configurable)
        model_run_config = _model_gateway_config(run_config)
        api_key = str(configurable.get("credentials", {}).get("api_key") or "")
        model_config = rebuild_model_config(serializable, api_key=api_key)
        # CX-5：ReAct 只注入短原生工具 + plan.tools_needed，不默认全量 MCP 长工具。
        tool_defs = [
            dict(definition)
            for definition in select_tool_defs(
                registry,
                mode="react",
                tools_needed=_plan_tools_needed(state),
            )
        ]
        native_tool_mode = model_config.tool_call_mode == "native"
        profile_id = profile_id_from_configurable(configurable)
        use_native_stream = native_stream_allowed(profile_id, model_config.tool_call_mode)
        if tool_defs and native_tool_mode:
            stage_input = NATIVE_TOOL_STAGE_INPUT
        elif tool_defs:
            stage_input = REACT_STAGE_INPUT
        else:
            stage_input = (
                NATIVE_TOOL_STAGE_INPUT if native_tool_mode else REACT_STAGE_INPUT
            ) + "\n（本轮无可用工具，请直接回答。）"
        observations_text = _inject_observations(state)
        # SK-1：图状态只带 skill_id；完整工作流按需装配，未启用技能在此 VALIDATION。
        skill_id = plan_skill_id(state)
        try:
            hints = skill_hints_for_turn(skill_id)
            workflow = load_skill_workflow(skill_id) if skill_id else None
        except AppError as exc:
            return _react_error_state(
                state,
                code=exc.code.value,
                message=exc.message,
            )
        # ws.py 的 agent_system_prompt 是协议档/平台配置的唯一入口，ReAct 只能在
        # 其后按 CX-4 装配 Skill Hint / 摘要 / 阶段输入，不能用固定 Persona 覆盖。
        configured_system = str(serializable.get("system") or "").strip()
        persona = configured_system or build_system_prompt(
            SystemVars(skill_hints=tuple(hints))
        )
        tool_hints = "\n".join(
            f"- {definition['name']}：{definition['description']}" for definition in tool_defs
        )
        stage_parts = [stage_input]
        if tool_hints:
            stage_parts.append("【本轮可用平台工具】\n" + tool_hints)
        task_state_data = state.get("task_state")
        current_task_state = (
            TaskSessionState.from_dict(task_state_data)
            if isinstance(task_state_data, Mapping)
            else None
        )
        if current_task_state is not None and state.get("observations"):
            current_task_state = evolve_task_state(
                current_task_state, tuple(state.get("observations") or ())
            )
            state["task_state"] = current_task_state.to_dict()

        plan_input = _plan_stage_input(state)
        if plan_input:
            stage_parts.append(plan_input)
        close_turn = not _has_active_plan(state)
        state_native_messages = tuple(state.get("native_messages") or ())
        native_messages = _hydrate_native_messages(
            state, native_tool_results, thread_id
        )
        # 原生 ToolResult 已作为 role=tool 消息传给模型，不能再把完整正文复制进
        # system。JSON ReAct 兼容路径若未写入 native_messages，仍必须注入
        # 【工具结果】，否则只输出协议 JSON 的模型会以为 read 没有返回。
        if observations_text and not state_native_messages:
            stage_parts.append(observations_text)
        assembled = assemble(
            system=persona,
            skill_hints=hints,
            skill_workflow=workflow,
            summary=compact_summary_from_configurable(configurable),
            stage_input="\n\n".join(part for part in stage_parts if part),
            messages=list(serializable.get("messages") or ()),
            tool_defs=tool_defs if native_tool_mode else None,
        )
        system = str(assembled["system"])
        request = ModelRequest(
            config=model_config,  # type: ignore[arg-type]
            messages=tuple(assembled["messages"]) + native_messages,
            system=system,
            tools=assembled["tools"] if native_tool_mode else (),
        )
        tool_payload_chars = sum(
            len(str(message.get("content") or ""))
            for message in native_messages
            if str(message.get("role") or "") == "tool"
        )
        agent_trace(
            f"model native_round tool_payload_chars={tool_payload_chars} "
            f"native_msgs={len(native_messages)} tools={len(tool_defs)} "
            f"stream={int(use_native_stream)}"
        )
        budget = from_dict(state.get("budget") or {})
        started = time.perf_counter()
        stream_attempted = False
        round_trace = _NativeRoundTrace()
        try:
            # native 每一轮（含首轮）优先走流式网关：工具前正文立即投影；完整
            # ToolCall 只在响应结束后进入下方 ToolNode。无 stream 的测试桩、
            # 灰度未覆盖的协议档回退 invoke。
            response = None
            if use_native_stream:
                stream_attempted = True
                streamed = _stream_native_tool_round(gateway, request, model_run_config)
                if streamed is not None:
                    response, round_trace = streamed
            if response is None:
                stream_attempted = False
                round_trace = _NativeRoundTrace(invoke_fallback=native_tool_mode)
                response = gateway.invoke(request, config=model_run_config)  # type: ignore[attr-defined]
        except AppError as exc:
            if exc.code == ErrorCode.UPSTREAM and not stream_attempted:
                _record_native_round(
                    round_trace, incomplete=True, upstream=True
                )
            return _react_error_state(state, code=exc.code.value, message=exc.message)
        except Exception:
            return _react_error_state(state, code="INTERNAL", message="模型调用失败")
        latency_ms = round((time.perf_counter() - started) * 1000)
        agent_trace(f"model native_round latency_ms={latency_ms} has_tool_calls={bool(response.tool_calls)}")
        try:
            budget = consume_model_call(budget)
            if response.tool_calls and native_tool_mode:
                # 原生 ToolCall：同一响应允许多个函数调用。图状态保存首项 + 队列，
                # ToolNode 按批次保序；只读波次在灰度开启时才并行，写/bash/任务仍串行。
                try:
                    native_calls = _validated_native_tool_calls(tuple(response.tool_calls))
                except AppError as exc:
                    if exc.code == ErrorCode.UPSTREAM:
                        _record_native_round(
                            round_trace, associate_error=True, upstream=True
                        )
                    return _react_error_state(
                        state, code=exc.code.value, message=exc.message
                    )
                _record_native_round(round_trace)
                native_calls, skipped_repeat, skipped_runs = _split_native_readonly_repeats(
                    state, native_calls
                )
                if not native_calls and skipped_repeat is not None:
                    narration = _stage_narration(response.text)
                    thought_events = (
                        [
                            make_event(
                                "assistant_message",
                                {
                                    "text": narration,
                                    "role": "assistant",
                                    "interim": True,
                                    "latency_ms": latency_ms,
                                },
                            )
                        ]
                        if narration
                        else []
                    )
                    if state.get("repeat_retry"):
                        return _forced_repeat_completion(
                            state=state,
                            gateway=gateway,
                            request=request,
                            model_run_config=model_run_config,
                            system=system,
                            budget=budget,
                            started=started,
                            pending_events=thought_events,
                            close_turn=close_turn,
                            response=response,
                        )
                    # 只读重复调用优先缓存回放：模型直接拿到与上次一致的内容，
                    # 省一轮「纠正→重试」往返；回放后仍无进展才升级为强制收尾。
                    cached_text = _cached_native_replay_text(
                        state, native_tool_results, thread_id,
                        skipped_repeat.name, skipped_repeat.arguments,
                    )
                    if (
                        cached_text
                        and native_tool_results is not None
                        and native_tool_results.put(
                            thread_id, skipped_repeat.call_id, cached_text
                        )
                    ):
                        return {
                            "pending_tool": None,
                            "pending_tools": [],
                            "pending_tool_batch": None,
                            "repeat_retry": True,
                            "native_messages": [
                                _native_tool_message((skipped_repeat,), response.text),
                                {
                                    "role": "tool",
                                    "tool_call_id": skipped_repeat.call_id,
                                    "name": skipped_repeat.name,
                                    "content": "",
                                },
                            ],
                            "pending_events": thought_events,
                            # 观察只留摘要（完整正文仅进单回合 store，不入检查点）
                            "observations": [
                                Observation(
                                    tool=skipped_repeat.name,
                                    text=(
                                        f"工具 {skipped_repeat.name} 重复调用已缓存回放，"
                                        "内容与上次成功执行完全一致。"
                                    ),
                                    ok=True,
                                    arguments=dict(skipped_repeat.arguments),
                                )
                            ],
                            "budget": budget.to_dict(),
                        }
                    return {
                        "pending_tool": None,
                        "pending_tools": [],
                        "pending_tool_batch": None,
                        "repeat_retry": True,
                        "pending_events": thought_events,
                        "observations": [
                            _repeat_correction_observation(
                                skipped_repeat.name,
                                dict(skipped_repeat.arguments),
                                skipped_runs,
                            )
                        ],
                        "budget": budget.to_dict(),
                    }
                for _ in native_calls:
                    budget = consume_tool_turn(budget)
                pending_calls = [
                    {
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                        "native": True,
                    }
                    for call in native_calls
                ]
                narration = _stage_narration(response.text)
                pending_events = (
                    [
                        make_event(
                            "assistant_message",
                            {
                                "text": narration,
                                "role": "assistant",
                                "interim": True,
                                "latency_ms": latency_ms,
                            },
                        )
                    ]
                    if narration
                    else []
                )
                # ToolCall 必须早于 ToolNode 的瞬态进度/输出帧落库并广播；前端
                # 因而可以始终按 call_id 原地更新同一张卡，而非等待工具结束才建卡。
                pending_events.extend(_tool_call_event(call) for call in pending_calls)
                result_payload = {
                    "pending_tool": pending_calls[0],
                    "pending_tools": pending_calls[1:],
                    "pending_tool_batch": build_tool_batch(pending_calls),
                    "native_messages": [_native_tool_message(native_calls, response.text)],
                    "pending_events": pending_events,
                    "repeat_retry": False,
                    "budget": budget.to_dict(),
                }
                if current_task_state is not None:
                    result_payload["task_state"] = current_task_state.to_dict()
                    # 演进后的状态黑板随事件下发，前端实时刷新任务看板
                    pending_events.append(
                        make_event("task_state", current_task_state.to_dict())
                    )
                return result_payload

            if native_tool_mode:
                _record_native_round(round_trace)

            if (
                native_tool_mode
                and state_native_messages
                and not _looks_like_legacy_react(response.text)
            ):
                # 此回合已由 _stream_native_tool_round 输出正文，不再追加第三次
                # 无工具模型调用；简单 "工具 → 结论" 路径因此固定为两次模型调用。
                text = response.text.strip() or FINAL_ANSWER_EMPTY_TEXT
                completed = _assistant_completion(
                    text,
                    usage=response.usage,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    close_turn=close_turn,
                    turn_stats=_turn_stats(state, budget, response.usage),
                )
                completed["budget"] = budget.to_dict()
                if current_task_state is not None:
                    completed["task_state"] = current_task_state.to_dict()
                    completed["pending_events"].append(
                        make_event("task_state", current_task_state.to_dict())
                    )
                return completed

            try:
                result = parse_react(response.text)
                fields = result["fields"]
            except AppError as exc:
                # 模型输出不符合 ReAct 协议（非有效 JSON/缺字段/类型错/版本不符）：
                # 注入纠正观察并回环重试（有界），而非直接硬错误收尾。
                parse_retries = int(state.get("parse_retries") or 0)
                if parse_retries >= MAX_PARSE_RETRIES:
                    return _react_error_state(
                        state,
                        code=exc.code.value,
                        message=exc.message,
                        parse_retries=parse_retries,
                        budget=budget.to_dict(),
                    )
                snippet = response.text.strip()
                correction = Observation(
                    tool="__parse__",
                    text=(
                        f"系统提示：上一轮输出无法解析为 ReAct 协议（{exc.message}）。"
                        f"你输出的原文是：{snippet[:500]!r}。"
                        "请只输出协议 JSON，不要附加说明文字、不要用代码块："
                        '{"protocol": "react", "version": "react.v1", "thought": "简述本轮判断", '
                        '"tool": "工具名或null", "arguments": {}, "done": false}'
                    ),
                    ok=False,
                    redacted=True,
                )
                return {
                    "pending_tool": None,
                    "repeat_retry": True,
                    "parse_retries": parse_retries + 1,
                    "pending_events": [],
                    # observations 为 append reducer，只返回本条新增，不重复携带旧列表
                    "observations": [correction],
                    "budget": budget.to_dict(),
                }
            thought = _extract_thought(response.text)
            thought_events = (
                [
                    make_event(
                        "thought",
                        {"text": thought, "stream": "think", "stage": "react"},
                    )
                ]
                if thought
                else []
            )
            if fields["done"]:
                # 工具指令守卫：用户明确要求调用工具但模型未调用任何工具就声称
                # 完成（反幻觉，生产实测 qwen 把"已成功更新"写进 thought 并
                # done=true）——拦截收尾，注入纠正观察强制先调用工具再作答。
                guard = _requested_tool_correction(state)
                if guard is not None:
                    return {
                        "pending_tool": None,
                        # repeat_retry=True 触发 react_route 回环 react_agent，
                        # 强制模型下一轮携带工具结果继续（否则图直接 end）。
                        "repeat_retry": True,
                        "pending_events": [],
                        "observations": [guard],
                        "budget": budget.to_dict(),
                    }
                # 工具已经执行过时，控制模型只负责判定收敛；再走一次无工具
                # 自然语言流式调用，正文通过 get_stream_writer 投影为 assistant_delta。
                final_response = None
                has_tool_observation = _has_tool_observation(state)
                if has_tool_observation:
                    budget = consume_model_call(budget)
                    final_response = _generate_final_answer(
                        gateway,
                        request,
                        model_run_config,
                        system=system,
                    )
                    latency_ms = round((time.perf_counter() - started) * 1000)
                # 工具链不再以 ReAct thought 作为最终交付句。最终模型回合为空时仅
                # 返回中性提示，避免控制协议或 Observation 原文泄露给用户。
                text = (
                    final_response.text
                    if final_response is not None and final_response.text.strip()
                    else FINAL_ANSWER_EMPTY_TEXT
                    if has_tool_observation
                    else _extract_thought(response.text) or "任务完成"
                )
                final_usage = (
                    dict(final_response.usage)
                    if final_response is not None
                    else dict(response.usage)
                )
                finished = _assistant_completion(
                    text,
                    usage=final_usage,
                    latency_ms=latency_ms,
                    close_turn=close_turn,
                    turn_stats=_turn_stats(state, budget, final_usage),
                )
                finished["budget"] = budget.to_dict()
                if current_task_state is not None:
                    finished["task_state"] = current_task_state.to_dict()
                    finished["pending_events"].append(
                        make_event("task_state", current_task_state.to_dict())
                    )
                return finished
            # 工具路径：重复调用抑制（OR-4）→ 预算 → 写 pending_tool
            # strip 兜底：模型输出工具名偶带尾随空白/换行（如 "read\n"），
            # 归一化后才能命中注册表与 READONLY_TOOLS 豁免，避免误报未注册。
            tool = str(fields.get("tool") or "").strip()
            arguments = dict(fields.get("arguments") or {})
            # 兼容 JSON ReAct 没有上游调用 ID，统一由平台生成，保证同名连续
            # 调用也能通过 call_id 在前端与 tool_result 精确配对。
            legacy_call_id = f"toolcall_{uuid4().hex}"
            # 仅当「工具名 + 参数」与已执行过的调用完全相同才视为重复；
            # 只比较工具名会把合法的连续 bash 调用（如 ls 后再 cat）误杀。
            # 只统计先前「成功」的相同调用：失败后的重试是模型合法行为
            # （工具瞬时失败/沙箱抖动时应有权重试），不应触发 OR-4。
            identical_count = _identical_success_count(
                state, tool, arguments, limit=READONLY_REPEAT_LIMIT
            )
            if identical_count and tool in READONLY_TOOLS:
                # 只读工具无进展重复：优先缓存回放（省一轮纠正往返），
                # 无缓存才退回纠正观察。
                if state.get("repeat_retry"):
                    return _forced_repeat_completion(
                        state=state,
                        gateway=gateway,
                        request=request,
                        model_run_config=model_run_config,
                        system=system,
                        budget=budget,
                        started=started,
                        pending_events=thought_events,
                        close_turn=close_turn,
                        response=response,
                    )
                cached_text = _cached_replay_text(state, tool, arguments)
                if cached_text:
                    return {
                        "pending_tool": None,
                        "repeat_retry": True,
                        "pending_events": thought_events,
                        "observations": [
                            _repeat_replay_observation(tool, arguments, cached_text, identical_count)
                        ],
                        "budget": budget.to_dict(),
                    }
                return {
                    "pending_tool": None,
                    "repeat_retry": True,
                    "pending_events": thought_events,
                    "observations": [
                        _repeat_correction_observation(tool, arguments, identical_count)
                    ],
                    "budget": budget.to_dict(),
                }
            if identical_count and tool not in READONLY_TOOLS:
                if state.get("repeat_retry"):
                    # 已给过一次纠正仍重复相同调用：判定未推进，硬错误收尾；
                    # 必须清 repeat_retry，否则 react_route 见到 True 会再次回环
                    # react_agent，模型调用预算被死循环耗尽（BUDGET_EXCEEDED）。
                    return _react_error_state(
                        state,
                        code="VALIDATION",
                        message=f"工具 {tool} 连续调用未推进，已终止",
                        extra_events=thought_events,
                        budget=budget.to_dict(),
                    )
                # 首次重复：注入纠正观察（不执行工具）并置 repeat_retry，
                # react_route 据此回环到 react_agent 让模型基于反馈换命令或收尾。
                return {
                    "pending_tool": None,
                    "repeat_retry": True,
                    "pending_events": thought_events,
                    # observations 为 append reducer，只返回本条新增纠正观察
                    "observations": [
                        Observation(
                            tool=tool,
                            text=(
                                f"系统提示：工具 {tool} 已用相同参数执行过（结果见上）。"
                                "请勿重复相同调用；请改用不同命令继续，或直接 done=true 完成回答。"
                            ),
                            ok=False,
                            redacted=True,
                            arguments=arguments,
                        )
                    ],
                    "budget": budget.to_dict(),
                }
            budget = consume_tool_turn(budget)  # 可能抛 BUDGET_EXCEEDED
            if state.get("repeat_retry"):
                # 重试回合中模型已换新调用，清除回环标记后正常执行
                return _json_react_tool_payload(
                    native_tool_mode=native_tool_mode,
                    call_id=legacy_call_id,
                    tool=tool,
                    arguments=arguments,
                    thought_events=list(thought_events),
                    budget=budget,
                    thought_text=thought,
                )
        except AppError as exc:
            # 协议解析失败/预算耗尽：转 error 收尾（不裸抛给用户堆栈）
            return _react_error_state(
                state,
                code=exc.code.value,
                message=exc.message,
                budget=budget.to_dict(),
            )
        pending = _json_react_tool_payload(
            native_tool_mode=native_tool_mode,
            call_id=legacy_call_id,
            tool=tool,
            arguments=arguments,
            thought_events=thought_events,
            budget=budget,
            thought_text=thought,
        )
        if current_task_state is not None:
            pending["task_state"] = current_task_state.to_dict()
        return pending

    return {"react_agent": react_agent_node}


def react_route(state: GraphState) -> str:
    """ReAct 条件边：pending_tool → tools；repeat_retry → 回环；
    turn_failed → 结束（有 plan 时已由本节点发出 completed(error)）；
    带 plan 则进入 reflect 统一收尾；否则图结束。"""
    if state.get("pending_tool"):
        return "tools"
    if state.get("repeat_retry"):
        return "react_agent"
    if state.get("turn_failed"):
        return "end"
    if _has_active_plan(state):
        return "reflect"
    return "end"


def tools_route(state: GraphState) -> str:
    """ToolNode 条件边：队列未空继续 tools；预算耗尽或回合失败则结束。

    默认预算 12/12 时 ``routing + n×(react+tools)`` 约 25 步，恰好顶到
    LangGraph 默认 ``recursion_limit=25``。若工具后再无条件回 ``react_agent``，
    第 13 次 ``consume_model_call`` 来不及抛 ``BUDGET_EXCEEDED`` 就会
    ``GraphRecursionError``。
    """
    if state.get("pending_tool"):
        return "tools"
    if state.get("turn_failed"):
        return "end"
    budget = from_dict(state.get("budget") or {})
    if is_budget_exhausted(budget):
        return "end"
    return "react_agent"
