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
from app.harness.context.observation import DEFAULT_MAX_CHARS
from app.harness.contracts import Observation, make_event
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
- 工具已返回内容即可基于内容直接作答；内容未读完也可直接 done=true 回答，不必强行读完。
- 禁止用完全相同参数重复调用已执行过的工具；如需继续，请换用不同命令，或直接 done=true 收尾。
可用工具（名称 + 参数要求）："""


# read 工具懒读取需要把文件内容完整送进模型上下文，突破默认 2000 字符观察截断。
# 上限与 read 默认 limit(8000) + 截断标记对齐，避免超大观察塞爆系统提示词
# 导致模型重复调用/不跟随协议。
READ_OBSERVATION_MAX_CHARS = 9_000

# 只读幂等工具：重复调用不判定"未推进"（OR-4 防重复守卫豁免）。
# read/web_fetch 重读/重抓无害且常是模型合法行为（如确认内容、重新获取），
# 若有副作用工具（write/edit/bash）才会被守卫约束；死循环由模型调用预算兜底。
READONLY_TOOLS: frozenset[str] = frozenset({"read", "web_fetch"})


def _inject_observations(state: GraphState) -> str:
    """把 observations 归一为摘要文本（M2 to_observation，脱敏在注入前）。"""
    observations = state.get("observations") or []
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
            result = parse_react(response.text)
            fields = result["fields"]
            # 每轮 ReAct 决策的 thought 透出为 thought 事件（PR-3：只回显不触发动作），
            # 让用户在工具调用过程中看到模型的思考过程。
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
                    "repeat_retry": False,  # 清除回环标记，react_route 据此正常结束
                    "budget": budget.to_dict(),
                }
            # 工具路径：重复调用抑制（OR-4）→ 预算 → 写 pending_tool
            tool = str(fields.get("tool") or "")
            arguments = dict(fields.get("arguments") or {})
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
                    "observations": list(observations)
                    + [
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
                    "pending_tool": {"name": tool, "arguments": arguments},
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
            "pending_tool": {"name": tool, "arguments": arguments},
            "pending_events": thought_events,
            "budget": budget.to_dict(),
        }

    return {"react_agent": react_agent_node}


def react_route(state: GraphState) -> str:
    """ReAct 条件边：pending_tool → 'tools'；repeat_retry → 回环 react_agent
    （OR-4 首次重复纠正后让模型基于反馈重试）；否则图结束。"""
    if state.get("pending_tool"):
        return "tools"
    if state.get("repeat_retry"):
        return "react_agent"
    return "end"
