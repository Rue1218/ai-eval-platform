"""Agent 纯对话节点（骨架版）。

图节点只返回纯数据（pending_events / response 投影），不持有 WebSocket
连接、不直接 emit；事件由 ws.py 收包循环统一翻译发出（§2.5 事件桥接契约）。
``should_abort`` 与 api_key 均从 ``RunnableConfig.configurable`` 读取，不入
GraphState。骨架版不再做范式路由（direct/chat/react/plan_solve），用户消息
一律直接装配上下文并调用模型生成回复。
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from langgraph.config import get_config, get_stream_writer

from app.errors import AppError, ErrorCode
from app.harness.context import (
    assemble,
    compact_summary_from_configurable,
    skill_hints_for_turn,
)
from app.harness.contracts import make_event
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
from app.harness.prompts import (
    DEFAULT_PROJECT_INSTRUCTIONS,
    SystemVars,
    build_system_prompt,
    build_system_prompt_parts,
)
from app.llm import ModelRequest
from app.llm.contracts import SystemSegment


def chat_stream_node(state: GraphState, gateway: object) -> dict:
    """纯对话流式节点：``assemble`` 装配上下文 → ModelGateway → 投影增量 + pending_events。

    - 骨架版不再区分范式：统一走 Chat 路径，不注入工具定义；
    - ``should_abort`` 从 ``RunnableConfig.configurable["abort"]`` 读取（O-12）；
    - ``api_key`` 从 ``configurable["credentials"]`` 即时注入，不进 State（M3-D2）；
    - 正文增量经 ``get_stream_writer`` 投影（瞬态帧，不落库）；
    - 收尾写 assistant_message / response.completed 事件意图与 response 投影。
    """
    serializable: SerializableRequest = state["request"]
    run_config = get_config()
    configurable = (run_config or {}).get("configurable") or {}
    api_key = str(configurable.get("credentials", {}).get("api_key") or "")
    model_config = rebuild_model_config(serializable, api_key=api_key)
    persona = str(serializable.get("system") or "").strip() or build_system_prompt(
        SystemVars(
            skill_hints=tuple(skill_hints_for_turn()),
            project_instructions=DEFAULT_PROJECT_INSTRUCTIONS,
        )
    )
    skill_hints = skill_hints_for_turn()
    summary = compact_summary_from_configurable(configurable)
    assembled = assemble(
        system=persona,
        skill_hints=skill_hints,
        summary=summary,
        messages=list(serializable.get("messages") or ()),
    )
    # H0 缓存边界：开关开启时挂分段（适配器据此打缓存断点），关闭时行为与
    # 骨架化版本一致（assembled["system"] 单字符串，字节级兼容）。
    from app.config import settings
    from app.harness.context import assemble_segments

    system_segments: tuple[SystemSegment, ...] = ()
    system_text = assembled["system"]
    if settings.prompt_cache_enabled:
        # 缓存开启时不再从已拼接的 persona 猜测边界：WS 受控层传入的
        # system_context 使 L1/L2、S2 和动态 L3 能被明确拆开。旧检查点或
        # 单测缺该上下文时使用安全默认值，仍不把 Overlay 误标为静态。
        context = serializable.get("system_context")
        if isinstance(context, Mapping):
            static_system = str(context.get("static_system") or "").strip()
            raw_hints = context.get("skill_hints")
            context_hints = (
                tuple(str(item) for item in raw_hints)
                if isinstance(raw_hints, list | tuple)
                else ()
            )
            overlay = str(context.get("overlay") or "").strip()
        else:
            parts = build_system_prompt_parts(
                SystemVars(
                    skill_hints=tuple(skill_hints),
                    project_instructions=DEFAULT_PROJECT_INSTRUCTIONS,
                )
            )
            static_system = parts.static_system
            context_hints = parts.skill_hints
            overlay = parts.overlay
        segments = assemble_segments(
            system=static_system,
            skill_hints=context_hints,
            overlay=overlay,
            summary=summary,
        )
        system_text = "\n\n".join(segment.text for segment in segments)
        system_segments = tuple(
            SystemSegment(text=segment.text, cacheable=segment.cacheable) for segment in segments
        )
    request = ModelRequest(
        config=model_config,  # type: ignore[arg-type]
        messages=tuple(assembled["messages"]),
        system=system_text,
        system_segments=system_segments,
        tools=(),  # 骨架版不注入工具定义
    )
    writer = get_stream_writer()
    final_response = None
    started = time.perf_counter()
    for event in gateway.stream(request, config=run_config):  # type: ignore[attr-defined]
        if event.kind == "completed":
            final_response = event.response
            continue
        writer({"kind": event.kind, "text": event.text})
    if final_response is None:
        raise AppError(ErrorCode.INTERNAL, "模型层未产生完整响应")
    latency_ms = round((time.perf_counter() - started) * 1000)
    # Router 审计字段（H1）：仅当 Router 已写入 engine 时附带（主开关关闭时
    # payload 与骨架化快照完全一致）；本节点只读不写，engine 本轮不可变。
    completed: dict[str, object] = {"finish_reason": "stop", "role": "assistant"}
    if state.get("engine"):
        completed.update(
            engine=state.get("engine"),
            router_confidence=float(state.get("router_confidence") or 0.0),
            router_reason=str(state.get("router_reason") or ""),
        )
    return {
        "pending_events": [
            make_event(
                "assistant_message",
                {
                    "text": final_response.text,
                    "role": "assistant",
                    "latency_ms": latency_ms,
                    # usage（含上游可用时的缓存读/创建 token）随既有 turn_stats
                    # 落库，供 O2/H6 在不新增 WS 事件的前提下观测缓存效果。
                    "turn_stats": {"usage": dict(final_response.usage)},
                },
            ),
            make_event("response.completed", completed),
        ],
        "response": {
            "text": final_response.text,
            "usage": dict(final_response.usage),
            "latency_ms": latency_ms,
        },
    }
