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

# Router L1 CoT 指令（H1，ADR-1）：要求输出 router.v1 JSON；reason 仅模型侧
# 推理，平台审计 reason 一律使用模板文案，不采纳模型原文（防用户文本回流）。
_ROUTER_L1_SYSTEM: str = """你是平台的请求分流器。仅输出一个 router.v1 JSON 对象（不要任何其他文字或代码块标记）：
{"engine": "direct|chat|workflow|agent", "skill_id": "skill-<id>|null", "confidence": <0到1的数字>, "reason": "<一句话中文理由>", "slots": {}, "protocol": "router", "version": "router.v1"}

engine 语义：
- direct：斜杠命令（如 /stop）
- chat：常规问答，无需工具或固定流程
- workflow：评测（benchmark）、用例生成（testcase）、知识库评测（rag）、压测（stress）等有固定槽位与流程的入队请求
- agent：需要多步探索、排查、读文件或工具链的开放任务
"""


def _latest_user_text(serializable: SerializableRequest) -> str:
    """提取本轮最后一条用户消息文本（图内分流输入；无则空串走 chat）。"""
    for message in reversed(serializable.get("messages") or ()):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(part for part in parts if part)
        return ""
    return ""


def router_node(state: GraphState, gateway: object) -> dict:
    """Router 节点（H1，ADR-1）：顶层引擎分流 + 审计三件套写 State。

    - L0 确定性纯函数（``decide_engine_l0``）先行，不调模型；
    - 仅当 L1 开关开启、非 direct 且置信度低于配置阈值时，做一次 L1 CoT
      短调用（受 router.v1 协议校验）；上游异常/超时/解析失败/预算异常
      一律回落 L0（失败必降级，保证引擎字段可复现）；
    - 只做分流：不创建任务、不加载工具、不执行长任务、不产出用户可见事件；
    - L1 计入 ``budget.model_calls``；审计 reason 恒为平台文案（脱敏）。
    """
    from app.config import settings
    from app.harness.orchestration.router import decide_engine_l0

    serializable: SerializableRequest = state["request"]
    text = _latest_user_text(serializable)
    verdict = decide_engine_l0(text)
    engine = verdict.engine
    confidence = verdict.confidence
    reason = verdict.reason
    budget = dict(state.get("budget") or {})
    if (
        settings.hybrid_router_cot_enabled
        and verdict.engine != "direct"
        and verdict.confidence < settings.hybrid_router_confidence_threshold
    ):
        budget["model_calls"] = budget.get("model_calls", 0) + 1
        try:
            adopted = _router_l1_call(serializable, state, gateway)
        except Exception:
            adopted = None  # AppError / 上游 / 超时 / 解析失败：一律回落 L0
        if adopted is not None:
            engine, l1_confidence = adopted
            confidence = l1_confidence
            reason = f"L0 低置信度，L1 CoT 复核采纳 engine={engine}（置信度 {confidence:.2f}）"
        else:
            reason = f"{verdict.reason}（L1 复核失败，回落 L0）"
    return {
        "engine": engine,
        "router_confidence": confidence,
        "router_reason": reason,
        "budget": budget,
    }


def _router_l1_call(
    serializable: SerializableRequest,
    state: GraphState,
    gateway: object,
) -> tuple[str, float] | None:
    """L1 CoT 短调用：router.v1 JSON 解析校验后返回 (engine, confidence)。

    解析失败（非法 JSON/多余字段/版本不符/置信度越界）抛异常由调用方回落；
    ``reason`` 与 ``slots`` 不在本层采纳（防用户文本回流审计与提前消费槽位）。
    """
    from dataclasses import replace

    from langgraph.config import get_config

    from app.harness.prompts import parse_router_v1

    run_config = get_config()
    configurable = (run_config or {}).get("configurable") or {}
    api_key = str(configurable.get("credentials", {}).get("api_key") or "")
    model_config = rebuild_model_config(serializable, api_key=api_key)
    request = ModelRequest(
        config=replace(model_config, max_tokens=256),  # L1 只产出小 JSON
        messages=tuple(serializable.get("messages") or ()),
        system=_ROUTER_L1_SYSTEM,
        tools=(),
    )
    response = gateway.invoke(request, config=run_config)  # type: ignore[attr-defined]
    result = parse_router_v1(str(getattr(response, "text", "") or ""))
    fields = result["fields"]
    l1_engine = str(fields.get("engine") or "")
    l1_confidence = float(fields.get("confidence") or 0.0)
    if not 0.0 <= l1_confidence <= 1.0:
        raise AppError(ErrorCode.VALIDATION, "L1 置信度越界")
    return l1_engine, l1_confidence


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

    segments = ()
    system_text = assembled["system"]
    if settings.prompt_cache_enabled:
        segments = assemble_segments(
            system=persona,
            skill_hints=skill_hints,
            summary=summary,
        )
        system_text = "\n\n".join(segment.text for segment in segments)
    request = ModelRequest(
        config=model_config,  # type: ignore[arg-type]
        messages=tuple(assembled["messages"]),
        system=system_text,
        system_segments=segments,
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
    # H1 审计载体（API.md：response.completed 增 engine/router_confidence/
    # router_reason，均为可选字段）：Router 开启时带分流痕迹；关闭时字段缺席，
    # 与骨架化旧客户端字节兼容（不新增 WS 事件类型）。
    completed_payload: dict[str, object] = {"finish_reason": "stop", "role": "assistant"}
    engine = state.get("engine")
    if engine is not None:
        completed_payload["engine"] = engine
        completed_payload["router_confidence"] = state.get("router_confidence")
        completed_payload["router_reason"] = state.get("router_reason")
    return {
        "pending_events": [
            make_event(
                "assistant_message",
                {"text": final_response.text, "role": "assistant", "latency_ms": latency_ms},
            ),
            make_event("response.completed", completed_payload),
        ],
        "response": {
            "text": final_response.text,
            "usage": dict(final_response.usage),
            "latency_ms": latency_ms,
        },
    }
