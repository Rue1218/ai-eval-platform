"""ReAct 循环子图节点（M4 阶段 2，OR-2/OR-4）。

``react_agent_node`` 每轮：装配上下文（系统策略 + 阶段输入 + observations 摘要
+ 工具定义最小注入）→ 非流式模型调用 → ``parse_react`` 严格解析 → 写
``pending_tool``（工具路径）或 done 收尾（对话路径）。``react_route`` 条件边
按 ``pending_tool`` 分流；预算在节点内消费（count-only，OR-5）；重复调用/
长路径抑制（OR-4）由「最近一次 tool 相同」检测并转 error 收尾。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from langgraph.config import get_config

from app.errors import AppError
from app.harness.context import to_observation
from app.harness.contracts import make_event
from app.harness.memory import GraphState, rebuild_model_config
from app.harness.orchestration import (
    consume_model_call,
    consume_tool_turn,
    from_dict,
)
from app.harness.prompts import SystemVars, build_system_prompt, parse_react
from app.llm import ModelRequest

# 阶段输入：ReAct 协议说明（M1 阶段输入，随节点注入，不做持久化）
REACT_STAGE_INPUT = """\
【当前阶段：ReAct 循环】
每轮输出严格 JSON（ReAct 协议 v1），禁止输出其他内容：
{"protocol": "react", "version": "react.v1", "thought": "简述本轮判断", "tool": "工具名或null", "arguments": {}, "done": false}
- 需要工具：tool 填工具名，arguments 填参数，done=false；
- 任务完成：tool=null，arguments={}，done=true。
可用工具（名称 + 参数要求）："""


def _inject_observations(state: GraphState) -> str:
    """把 observations 归一为摘要文本（M2 to_observation，脱敏在注入前）。"""
    observations = state.get("observations") or []
    if not observations:
        return ""
    lines = [to_observation(observation) for observation in observations]
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


def build_react_nodes(
    gateway: object,
    registry: object,
) -> dict[str, Callable]:
    """构造 ReAct 节点：{'react_agent': ...}；条件边路由见 ``react_route``。"""

    def react_agent_node(state: GraphState) -> dict:
        serializable = state["request"]
        run_config = get_config()
        configurable = (run_config or {}).get("configurable") or {}
        api_key = str(configurable.get("credentials", {}).get("api_key") or "")
        model_config = rebuild_model_config(serializable, api_key=api_key)
        tool_defs = [
            dict(definition)
            for definition in (registry.all_defs() if hasattr(registry, "all_defs") else [])
        ]
        if tool_defs:
            stage_input = REACT_STAGE_INPUT + "\n" + "\n".join(
                f"- {definition['name']}：{definition['description']}"
                for definition in tool_defs
            )
        else:
            stage_input = REACT_STAGE_INPUT + "（无可用工具）"
        observations_text = _inject_observations(state)
        # 把本回合可用工具接入 skill_hints，避免系统策略"可见技能：（无）"
        # 与 ReAct 工具列表矛盾，导致模型误判工具未启用而拒绝调用。
        system = build_system_prompt(
            SystemVars(
                skill_hints=tuple(
                    f"{definition['name']}：{definition['description']}"
                    for definition in tool_defs
                )
            )
        )
        if observations_text:
            system = system + "\n\n" + observations_text
        request = ModelRequest(
            config=model_config,  # type: ignore[arg-type]
            messages=serializable.get("messages") or (),
            system=system + "\n\n" + stage_input,
            tools=tool_defs,
        )
        budget = from_dict(state.get("budget") or {})
        started = time.perf_counter()
        try:
            response = gateway.invoke(request, config=run_config)  # type: ignore[attr-defined]
        except AppError as exc:
            return {
                "pending_events": [
                    make_event(
                        "error",
                        {"code": exc.code.value, "message": exc.message},
                    )
                ],
                "pending_tool": None,
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
            }
        latency_ms = round((time.perf_counter() - started) * 1000)
        try:
            budget = consume_model_call(budget)
            result = parse_react(response.text)
            fields = result["fields"]
            if fields["done"]:
                # 对话路径收尾：assistant_message + response.completed
                # （thought 只回显不触发动作，PR-3）
                text = _extract_thought(response.text) or "任务完成"
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
                        "usage": dict(response.usage),
                        "latency_ms": latency_ms,
                    },
                    "budget": budget.to_dict(),
                }
            # 工具路径：重复调用抑制（OR-4）→ 预算 → 写 pending_tool
            tool = str(fields.get("tool") or "")
            arguments = dict(fields.get("arguments") or {})
            observations = state.get("observations") or []
            if observations and getattr(observations[-1], "tool", None) == tool:
                return {
                    "pending_events": [
                        make_event(
                            "error",
                            {"code": "VALIDATION", "message": f"工具 {tool} 连续调用未推进，已终止"},
                        )
                    ],
                    "pending_tool": None,
                    "budget": budget.to_dict(),
                }
            budget = consume_tool_turn(budget)  # 可能抛 BUDGET_EXCEEDED
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
                "budget": budget.to_dict(),
            }
        return {
            "pending_tool": {"name": tool, "arguments": arguments},
            "budget": budget.to_dict(),
        }

    return {"react_agent": react_agent_node}


def react_route(state: GraphState) -> str:
    """ReAct 条件边：pending_tool 存在 → 'tools'，否则图结束。"""
    if state.get("pending_tool"):
        return "tools"
    return "end"
