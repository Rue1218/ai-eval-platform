"""Agent 纯对话节点（骨架版）。

图节点只返回纯数据（pending_events / response 投影），不持有 WebSocket
连接、不直接 emit；事件由 ws.py 收包循环统一翻译发出（§2.5 事件桥接契约）。
``should_abort`` 与 api_key 均从 ``RunnableConfig.configurable`` 读取，不入
GraphState。骨架版不再做范式路由（direct/chat/react/plan_solve），用户消息
一律直接装配上下文并调用模型生成回复。
"""

from __future__ import annotations

import time

from langgraph.config import get_config, get_stream_writer

from app.errors import AppError, ErrorCode
from app.harness.context import (
    assemble,
    compact_summary_from_configurable,
    skill_hints_for_turn,
)
from app.harness.contracts import make_event
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
from app.harness.prompts import SystemVars, build_system_prompt
from app.llm import ModelRequest


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
        SystemVars(skill_hints=tuple(skill_hints_for_turn()))
    )
    assembled = assemble(
        system=persona,
        skill_hints=skill_hints_for_turn(),
        summary=compact_summary_from_configurable(configurable),
        messages=list(serializable.get("messages") or ()),
    )
    request = ModelRequest(
        config=model_config,  # type: ignore[arg-type]
        messages=tuple(assembled["messages"]),
        system=assembled["system"],
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
    return {
        "pending_events": [
            make_event(
                "assistant_message",
                {"text": final_response.text, "role": "assistant", "latency_ms": latency_ms},
            ),
            make_event(
                "response.completed",
                {"finish_reason": "stop", "role": "assistant"},
            ),
        ],
        "response": {
            "text": final_response.text,
            "usage": dict(final_response.usage),
            "latency_ms": latency_ms,
        },
    }
