"""ReAct 循环子图节点（M4 阶段 2，OR-2/OR-4）。

``react_agent_node`` 每轮：装配上下文（系统策略 + 阶段输入 + observations 摘要
+ 工具定义最小注入）→ 结构化模型调用 → ``parse_react`` 严格解析 → 写
``pending_tool``（工具路径）或完成后切换到自然语言流式回答（对话路径）。
``react_route`` 条件边按 ``pending_tool`` 分流；预算在节点内消费（count-only，
OR-5）；重复调用/长路径抑制（OR-4）由「最近一次 tool 相同」检测并转 error
收尾。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from uuid import uuid4

from langgraph.config import get_config, get_stream_writer

from app.adapters import StreamAborted
from app.errors import AppError, ErrorCode
from app.harness.context import to_observation
from app.harness.context.observation import DEFAULT_MAX_CHARS
from app.harness.contracts import Observation, make_event
from app.harness.execution import NativeToolResultStore, runtime_thread_id
from app.harness.memory import GraphState, rebuild_model_config
from app.harness.orchestration import (
    consume_model_call,
    consume_tool_turn,
    from_dict,
)
from app.harness.prompts import SystemVars, build_system_prompt, parse_react
from app.llm import ModelRequest, ModelResponse, NativeToolCall

# 阶段输入：ReAct 协议说明（M1 阶段输入，随节点注入，不做持久化）
REACT_STAGE_INPUT = """\
【当前阶段：ReAct 循环】
每轮输出严格 JSON（ReAct 协议 v1），禁止输出其他内容：
{"protocol": "react", "version": "react.v1", "thought": "简述本轮判断", "tool": "工具名或null", "arguments": {}, "done": false}
- 需要工具：tool 填工具名，arguments 填参数，done=false；
- 任务完成：tool=null，arguments={}，done=true。
- 工具已返回内容即可基于内容直接作答；内容未读完也可直接 done=true 回答，不必强行读完。
- 禁止用完全相同参数重复调用已执行过的工具；如需继续，请换用不同命令，或直接 done=true 收尾。
可用工具（名称 + 参数要求）："""

# P2 默认优先走上游原生 ToolCall。工具 schema 由 ModelRequest.tools 透传，
# 不再要求支持 function calling 的模型把控制动作伪装为正文 JSON；旧协议 JSON
# 仍由下方兼容分支解析，便于逐个协议档迁移。
NATIVE_TOOL_STAGE_INPUT = """\
【当前阶段：原生工具调用】
如需访问平台工具，请使用模型协议提供的原生函数调用能力，并只从本轮提供的工具
schema 中选择。工具结果会以对应的 tool_call_id 返回；请基于结果继续调用必要工具，
或直接给出自然语言结论。不要在正文中伪造工具调用 JSON、不要逐字回显工具原文。
同一请求中的多个函数调用会由平台依次执行，每一个调用都经过权限门禁和沙箱。
"""


# read 工具以整行返回、最多 120000 字符；完整片段只进入模型 Observation，
# ToolCard 另走 500 字符受控预览。后续由 profile 上下文预算动态收紧。
READ_OBSERVATION_MAX_CHARS = 120_000

# 只读幂等工具：重复调用不判定"未推进"（OR-4 防重复守卫豁免）。
# read/web_fetch 重读/重抓无害且常是模型合法行为（如确认内容、重新获取），
# 若有副作用工具（write/edit/bash）才会被守卫约束；死循环由模型调用预算兜底。
READONLY_TOOLS: frozenset[str] = frozenset({"read", "web_fetch"})

# 只读工具「相同参数」成功调用的容忍上限：允许少量重读（内容确认无害），
# 但无进展的反复相同调用（如 DeepSeek 反复 read 同一文件不传 offset）必须
# 收敛——超限注入纠正观察（提示传 offset 或直接作答），纠正后仍重复才硬错误。
READONLY_REPEAT_LIMIT = 3

# ReAct 协议解析失败纠正重试上限：模型输出非有效 JSON 时注入纠正观察并回环
# 一次（OR-4 同一回环边），仍失败才硬错误收尾；由模型调用预算兜底防死循环。
MAX_PARSE_RETRIES = 2

# 上下文注入最近观察条数上限：observations 已改为累积（OR-4 守卫需全量），
# 但注入系统提示只需最近若干条，避免长任务上下文无限膨胀（守卫仍看全量）。
INJECT_OBSERVATIONS_MAX = 6

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

logger = logging.getLogger("ai-eval.agent-react")


def _inject_observations(state: GraphState) -> str:
    """把 observations 归一为摘要文本（M2 to_observation，脱敏在注入前）。

    只注入最近 ``INJECT_OBSERVATIONS_MAX`` 条：模型作答依赖最近工具结果即可，
    守卫（identical_runs）仍消费全量累积观察。
    """
    observations = (state.get("observations") or [])[-INJECT_OBSERVATIONS_MAX:]
    if not observations:
        return ""
    lines = [
        to_observation(
            observation,
            max_chars=READ_OBSERVATION_MAX_CHARS if observation.tool == "read" else DEFAULT_MAX_CHARS,
        )
        for observation in observations
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
    for raw in state.get("native_messages") or ():
        message = dict(raw)
        if str(message.get("role") or "") == "tool":
            call_id = str(message.get("tool_call_id") or "")
            content = (
                native_tool_results.get(thread_id, call_id)
                if native_tool_results is not None
                else None
            )
            message["content"] = content or "工具结果在当前会话中不可用，请向用户说明并请求重试。"
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


def _assistant_completion(
    text: str,
    *,
    usage: dict[str, int] | object,
    latency_ms: int,
    pending_events: list[dict] | None = None,
) -> dict[str, object]:
    """统一构造自然语言收尾投影，避免原生/兼容路径产生不同事件契约。"""
    events = list(pending_events or [])
    events.extend(
        [
            make_event(
                "assistant_message",
                {"text": text, "role": "assistant", "latency_ms": latency_ms},
            ),
            make_event(
                "response.completed",
                {"finish_reason": "stop", "role": "assistant"},
            ),
        ]
    )
    return {
        "pending_events": events,
        "response": {"text": text, "usage": dict(usage or {}), "latency_ms": latency_ms},
        "pending_tool": None,
        "pending_tools": [],
        "repeat_retry": False,
    }


def _has_tool_observation(state: GraphState) -> bool:
    """判断当前 ReAct 回合是否已经执行过真实工具。"""
    return any(
        str(getattr(observation, "tool", "") or "") not in ("", "__parse__")
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
        serializable = state["request"]
        run_config = get_config()
        configurable = (run_config or {}).get("configurable") or {}
        thread_id = runtime_thread_id(configurable)
        model_run_config = _model_gateway_config(run_config)
        api_key = str(configurable.get("credentials", {}).get("api_key") or "")
        model_config = rebuild_model_config(serializable, api_key=api_key)
        tool_defs = [
            dict(definition)
            for definition in (registry.all_defs() if hasattr(registry, "all_defs") else [])
        ]
        native_tool_mode = model_config.tool_call_mode == "native"
        if tool_defs and native_tool_mode:
            stage_input = NATIVE_TOOL_STAGE_INPUT
        elif tool_defs:
            stage_input = REACT_STAGE_INPUT
        else:
            stage_input = (
                NATIVE_TOOL_STAGE_INPUT if native_tool_mode else REACT_STAGE_INPUT
            ) + "\n（本轮无可用工具，请直接回答。）"
        observations_text = _inject_observations(state)
        # ws.py 的 agent_system_prompt 是协议档/平台配置的唯一入口，ReAct 只能在
        # 其后追加本轮工具约束，不能重建固定 system 覆盖用户配置。
        configured_system = str(serializable.get("system") or "").strip()
        tool_hints = "\n".join(
            f"- {definition['name']}：{definition['description']}" for definition in tool_defs
        )
        system = configured_system or build_system_prompt(
            SystemVars(
                skill_hints=tuple(
                    f"{definition['name']}：{definition['description']}"
                    for definition in tool_defs
                )
            )
        )
        if tool_hints:
            system += "\n\n【本轮可用平台工具】\n" + tool_hints
        state_native_messages = tuple(state.get("native_messages") or ())
        native_messages = _hydrate_native_messages(
            state, native_tool_results, thread_id
        )
        # 原生 ToolResult 已作为 role=tool 消息传给模型，不能再把完整正文复制进
        # system；兼容 JSON ReAct 仍沿用 Observation 注入，保证旧协议档不回归。
        if observations_text and not state_native_messages:
            system = system + "\n\n" + observations_text
        request = ModelRequest(
            config=model_config,  # type: ignore[arg-type]
            messages=tuple(serializable.get("messages") or ()) + native_messages,
            system=system + "\n\n" + stage_input,
            tools=tool_defs if native_tool_mode else (),
        )
        budget = from_dict(state.get("budget") or {})
        started = time.perf_counter()
        try:
            response = gateway.invoke(request, config=model_run_config)  # type: ignore[attr-defined]
        except AppError as exc:
            return {
                "pending_events": [
                    make_event(
                        "error",
                        {"code": exc.code.value, "message": exc.message},
                    )
                ],
                "pending_tool": None,
                "repeat_retry": False,
            }
        except Exception:
            return {
                "pending_events": [
                    make_event(
                        "error",
                        {"code": "INTERNAL", "message": "模型调用失败"},
                    )
                ],
                "pending_tool": None,
                "repeat_retry": False,
            }
        latency_ms = round((time.perf_counter() - started) * 1000)
        try:
            budget = consume_model_call(budget)
            if response.tool_calls and native_tool_mode:
                # 原生 ToolCall：同一响应允许多个函数调用。图状态保存首项 + 队列，
                # ToolNode 仍逐项走既有 gate/binding/dispatch/bwrap 边界，不把模型
                # 参数直接送入 handler。
                native_calls = _validated_native_tool_calls(tuple(response.tool_calls))
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
                return {
                    "pending_tool": pending_calls[0],
                    "pending_tools": pending_calls[1:],
                    "native_messages": [_native_tool_message(native_calls, response.text)],
                    "pending_events": [],
                    "repeat_retry": False,
                    "budget": budget.to_dict(),
                }

            if state_native_messages and not _looks_like_legacy_react(response.text):
                # 支持原生调用的模型在工具结果后会直接返回自然语言。为保持工具后
                # 正文可流式展示，先把它作为收敛判断，再追加一轮无工具流式回答；
                # 首轮无工具时则直接采用该回答，避免无意义的双调用。
                has_native_tool_result = any(
                    str(message.get("role") or "") == "tool" for message in native_messages
                )
                final_response = None
                if has_native_tool_result:
                    budget = consume_model_call(budget)
                    final_response = _generate_final_answer(
                        gateway,
                        request,
                        model_run_config,
                        system=system,
                    )
                text = (
                    final_response.text
                    if final_response is not None and final_response.text.strip()
                    else response.text.strip() or FINAL_ANSWER_EMPTY_TEXT
                )
                completed = _assistant_completion(
                    text,
                    usage=(final_response.usage if final_response is not None else response.usage),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
                completed["budget"] = budget.to_dict()
                return completed

            try:
                result = parse_react(response.text)
                fields = result["fields"]
            except AppError as exc:
                # 模型输出不符合 ReAct 协议（非有效 JSON/缺字段/类型错/版本不符）：
                # 注入纠正观察并回环重试（有界），而非直接硬错误收尾。
                parse_retries = int(state.get("parse_retries") or 0)
                if parse_retries >= MAX_PARSE_RETRIES:
                    return {
                        "pending_events": [
                            make_event(
                                "error",
                                {"code": exc.code.value, "message": exc.message},
                            )
                        ],
                        "pending_tool": None,
                        "repeat_retry": False,
                        "parse_retries": parse_retries,
                        "budget": budget.to_dict(),
                    }
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
                return {
                    "pending_events": [
                        make_event(
                            "assistant_message",
                            {"text": text, "role": "assistant", "latency_ms": latency_ms},
                        ),
                        make_event(
                            "response.completed",
                            {"finish_reason": "stop", "role": "assistant"},
                        ),
                    ],
                    "response": {
                        "text": text,
                        "usage": final_usage,
                        "latency_ms": latency_ms,
                    },
                    "repeat_retry": False,  # 清除回环标记，react_route 据此正常结束
                    "budget": budget.to_dict(),
                }
            # 工具路径：重复调用抑制（OR-4）→ 预算 → 写 pending_tool
            # strip 兜底：模型输出工具名偶带尾随空白/换行（如 "read\n"），
            # 归一化后才能命中注册表与 READONLY_TOOLS 豁免，避免误报未注册。
            tool = str(fields.get("tool") or "").strip()
            arguments = dict(fields.get("arguments") or {})
            # 兼容 JSON ReAct 没有上游调用 ID，统一由平台生成，保证同名连续
            # 调用也能通过 call_id 在前端与 tool_result 精确配对。
            legacy_call_id = f"toolcall_{uuid4().hex}"
            observations = state.get("observations") or []
            # 仅当「工具名 + 参数」与已执行过的调用完全相同才视为重复；
            # 只比较工具名会把合法的连续 bash 调用（如 ls 后再 cat）误杀。
            def _same_call(obs: object) -> bool:
                return (
                    getattr(obs, "tool", None) == tool
                    and dict(getattr(obs, "arguments", None) or {}) == arguments
                )

            # 只统计先前「成功」的相同调用：失败后的重试是模型合法行为
            # （工具瞬时失败/沙箱抖动时应有权重试），不应触发 OR-4。
            identical_runs = [
                obs for obs in observations if _same_call(obs) and getattr(obs, "ok", False)
            ]
            if identical_runs and tool in READONLY_TOOLS and len(identical_runs) >= READONLY_REPEAT_LIMIT:
                # 只读工具无进展重复：相同参数已成功执行多次（返回内容必然相同），
                # 模型既未传 offset 继续读取也未作答，判定为循环。先注入纠正观察
                # （提示传 offset 或直接作答）；纠正后仍重复相同调用则基于已读内容
                # 优雅收尾——弱模型（如 DeepSeek V4 Flash）纠正无效、无法收敛到
                # done，硬错误只会让用户拿到报错而非内容。
                if state.get("repeat_retry"):
                    # 第二次仍重复时停止工具循环，但必须交由无工具模型回合生成
                    # 最终答案。禁止把 Observation.text（尤其是 read 原文）直接写成
                    # assistant_message，否则会绕过用户要求的分析、推理和总结。
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
                    return {
                        "pending_events": thought_events
                        + [
                            make_event(
                                "assistant_message",
                                {"text": text, "role": "assistant", "latency_ms": latency_ms},
                            ),
                            make_event(
                                "response.completed",
                                {"finish_reason": "stop", "role": "assistant"},
                            ),
                        ],
                        "response": {
                            "text": text,
                            "usage": (
                                dict(final_response.usage)
                                if final_response is not None
                                else dict(response.usage)
                            ),
                            "latency_ms": latency_ms,
                        },
                        "pending_tool": None,
                        "repeat_retry": False,
                        "budget": budget.to_dict(),
                    }
                return {
                    "pending_tool": None,
                    "repeat_retry": True,
                    "pending_events": thought_events,
                    # observations 为 append reducer，只返回本条新增纠正观察
                    "observations": [
                        Observation(
                            tool=tool,
                            text=(
                                f"系统提示：工具 {tool} 已用相同参数成功执行 {len(identical_runs)} 次，"
                                "返回内容完全相同，继续相同调用不会得到新信息。"
                                "如需读取未读部分：请改用不同参数（如 read 传 offset/limit 分段读取）；"
                                "如已读内容足够：请直接 done=true 完成回答，不要再用相同参数调用。"
                            ),
                            ok=False,
                            redacted=True,
                            arguments=arguments,
                        )
                    ],
                    "budget": budget.to_dict(),
                }
            if identical_runs and tool not in READONLY_TOOLS:
                if state.get("repeat_retry"):
                    # 已给过一次纠正仍重复相同调用：判定未推进，硬错误收尾；
                    # 必须清 repeat_retry，否则 react_route 见到 True 会再次回环
                    # react_agent，模型调用预算被死循环耗尽（BUDGET_EXCEEDED）。
                    return {
                        "pending_events": thought_events
                        + [
                            make_event(
                                "error",
                                {"code": "VALIDATION", "message": f"工具 {tool} 连续调用未推进，已终止"},
                            )
                        ],
                        "pending_tool": None,
                        "repeat_retry": False,
                        "budget": budget.to_dict(),
                    }
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
                return {
                    "pending_tool": {
                        "call_id": legacy_call_id,
                        "name": tool,
                        "arguments": arguments,
                        "native": False,
                    },
                    "pending_tools": [],
                    "repeat_retry": False,
                    "pending_events": thought_events,
                    "budget": budget.to_dict(),
                }
        except AppError as exc:
            # 协议解析失败/预算耗尽：转 error 收尾（不裸抛给用户堆栈）
            return {
                "pending_events": [
                    make_event(
                        "error",
                        {"code": exc.code.value, "message": exc.message},
                    )
                ],
                "pending_tool": None,
                "repeat_retry": False,
                "budget": budget.to_dict(),
            }
        return {
            "pending_tool": {
                "call_id": legacy_call_id,
                "name": tool,
                "arguments": arguments,
                "native": False,
            },
            "pending_tools": [],
            "pending_events": thought_events,
            "budget": budget.to_dict(),
        }

    return {"react_agent": react_agent_node}


def react_route(state: GraphState) -> str:
    """ReAct 条件边：pending_tool → 'tools'；repeat_retry → 回环 react_agent
    （OR-4 重复纠正 / 协议解析失败纠正后让模型基于反馈重试）；否则图结束。"""
    if state.get("pending_tool"):
        return "tools"
    if state.get("repeat_retry"):
        return "react_agent"
    return "end"
