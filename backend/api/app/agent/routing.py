"""Agent 图路由与 Direct/Chat 节点（M4 阶段 1，OR-1）。

图节点只返回纯数据（mode / pending_events / response 投影），不持有
WebSocket 连接、不直接 emit；事件由 ws.py 收包循环统一翻译发出（§2.5 事件
桥接契约）。``should_abort`` 与 api_key 均从 ``RunnableConfig.configurable``
读取，不入 GraphState。
"""

from __future__ import annotations

import time

from langgraph.config import get_config, get_stream_writer

from app.errors import AppError, ErrorCode
from app.harness.contracts import make_event
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
from app.harness.orchestration import AgentMode, decide_mode, detect_plan_intent
from app.llm import ModelRequest

# /help 帮助文本（阶段 1 硬编码占位，M4-Q4 裁决；后续从 M1 system.py 读取）
HELP_TEXT = (
    "我是 AI 测试与评估平台的评测助手，可以协助你完成大模型基准评测、用例生成"
    "与知识库评测任务。\n\n"
    "可用命令：\n"
    "- /help：查看帮助\n"
    "- /stop：中断当前生成\n"
    "- /compact：压缩本会话模型窗口（仅会话负责人）\n"
    "- /cancel、/stress：后续版本开放"
)


def user_text_from_state(state: GraphState) -> str:
    """从可序列化请求投影中取最近一条 user 消息文本（不含回调）。"""
    request = state.get("request") or {}
    messages = request.get("messages") or ()
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                text = "\n".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()
                if text:
                    return text
    return ""


def _config_has_attachments() -> bool:
    """从 configurable.assets.file_ids 判断当前回合是否带附件（触发 react）。"""
    configurable = (get_config() or {}).get("configurable") or {}
    return bool(configurable.get("assets", {}).get("file_ids") or ())


def routing_node(state: GraphState) -> dict:
    """路由节点：写 state['mode']，不调模型（OR-1 / P0）。

    带附件时强制 react（模型需 read 工具读取附件，chat 路径无工具注入）。
    多技能/确认卡/显式清单走 plan_solve，由规划节点调用 ``build_plan``。
    """
    text = user_text_from_state(state)
    return {
        "mode": decide_mode(
            text,
            has_attachments=_config_has_attachments(),
            has_multi_slots=detect_plan_intent(text),
        )
    }


def route(state: GraphState) -> AgentMode:
    """路由条件边函数：读 routing_node 写入的 mode，返回分流模式。"""
    text = user_text_from_state(state)
    return state.get("mode") or decide_mode(
        text,
        has_attachments=_config_has_attachments(),
        has_multi_slots=detect_plan_intent(text),
    )


def direct_node(state: GraphState) -> dict:
    """Direct 节点：L0 规则匹配已知斜杠，不调模型（M4 §3.6）。

    返回 {'pending_events': [NodeEvent, ...]}：
    - /help → assistant_message（帮助文本）
    - /compact /cancel /stress（阶段 1 未启用）→ error(VALIDATION)
    - 未知斜杠 → error(VALIDATION)
    """
    text = user_text_from_state(state)
    command = text.split()[0].lower() if text else ""
    if command == "/help":
        return {
            "pending_events": [
                make_event(
                    "assistant_message",
                    {"text": HELP_TEXT, "role": "assistant"},
                )
            ]
        }
    if command == "/compact":
        # /compact 为会话级副作用（仅 owner，写 compact_summary），唯一入口是
        # ws.py 收包循环直连；图节点不持 DB，此处为不可达路径的防御提示。
        return {
            "pending_events": [
                make_event(
                    "error",
                    {"code": "VALIDATION", "message": "/compact 由平台会话控制处理，无需发送"},
                )
            ]
        }
    if command in ("/cancel", "/stress"):
        return {
            "pending_events": [
                make_event(
                    "error",
                    {"code": "VALIDATION", "message": f"{command} 能力未启用，将在后续版本开放"},
                )
            ]
        }
    if command == "/stop":
        return {
            "pending_events": [
                make_event(
                    "error",
                    {"code": "VALIDATION", "message": "/stop 由平台即时中断处理，无需发送"},
                )
            ]
        }
    return {
        "pending_events": [
            make_event(
                "error",
                {"code": "VALIDATION", "message": f"未知斜杠命令：{command or '（空）'}"},
            )
        ]
    }


def chat_stream_node(state: GraphState, gateway: object) -> dict:
    """Chat 流式节点：重建 ModelRequest → ModelGateway → 投影增量 + pending_events。

    - ``should_abort`` 从 ``RunnableConfig.configurable["abort"]`` 读取（O-12）；
    - ``api_key`` 从 ``configurable["credentials"]`` 即时注入，不进 State（M3-D2）；
    - 正文/推理增量经 ``get_stream_writer`` 投影（瞬态帧，不落库）；
    - 收尾写 assistant_message / response.completed 事件意图与 response 投影。
    """
    serializable: SerializableRequest = state["request"]
    run_config = get_config()
    configurable = (run_config or {}).get("configurable") or {}
    api_key = str(configurable.get("credentials", {}).get("api_key") or "")
    model_config = rebuild_model_config(serializable, api_key=api_key)
    request = ModelRequest(
        config=model_config,  # type: ignore[arg-type]
        messages=serializable.get("messages") or (),
        system=serializable.get("system"),
        tools=serializable.get("tools") or (),
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
