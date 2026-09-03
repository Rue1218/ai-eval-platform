"""混合引擎 H3：Agent 分支 TAOR 主循环节点（plan → discover → orchestrator ⇄ tools）。

engine=agent 的子图语义（开发计划 H3 + 架构 ADR-2）：

    plan → discover → orchestrator【哑】⇄ tools【哑】

- ``plan`` 节点：一次模型调用产 ``plan.v1``（3–7 步进 ``slots.steps``）；
  解析失败降级 ``build_plan`` L0 关键词规则（不重试、不再调模型）；
- ``discover`` 节点：零模型调用，``AgentRegistry.discover`` 按能力/技能确定性
  选 Worker 并收窄 ``allowed_tools``；``worker.sandbox`` 永不可选中（fail-closed，
  H5 前 code 能力不放行）；视野任何一项必须已注册（fail-fast）；
- ``orchestrator`` 节点【哑】：Observe（注入 Observation）→ 调模型 Think →
  取 Act（react.v1）；不改写模型意图、不自动重试有副作用工具；
- ``tools`` 节点【哑】：复用 ``toolnode.build_tool_node`` 十层链（Schema →
  门禁 → 权限 → 并发 → 脱敏），结果回灌 Observation（只作模型输入）。

守卫（S2 / H3 硬门槛，全部就地收尾，无静默钳制）：
- 预算：``budget.model_calls`` / ``tool_turns`` count-only；耗尽 BUDGET_EXCEEDED；
- ``parse_retries ≤ 2``：协议解析失败重试上限，超限 turn_failed；
- 同参只读工具重复三次：OR-4 重复守卫，第四次 Act 前就地收尾；
- ``plan_step_index`` 越界（slots.steps 长度，缺省 7）：直接 turn_failed；
- 非法工具名 / 未注册工具：统一 VALIDATION 就地收尾（模型不可越权视野）。
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from langgraph.config import get_config

from app.errors import AppError
from app.harness.contracts import PlanArtifact, make_event, to_dict
from app.harness.contracts.artifacts import validate_plan_artifact
from app.harness.execution.toolnode import seal_budget_if_exhausted
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
from app.harness.orchestration import plan as plan_lib
from app.harness.orchestration.budget import (
    consume_model_call,
    consume_tool_turn,
    from_dict,
    is_budget_exhausted,
)
from app.harness.prompts.protocols import parse_plan_protocol, parse_react
from app.llm import ModelRequest

# ── 常量 ──

# 观察注入上限：模型输入只送最近若干条、单条截断（Observation 只作模型输入）。
# 预算 tool_turns ≤ 12，窗口 12 保证全链路观察都可回灌。
_MAX_INJECTED_OBSERVATIONS = 12
_MAX_OBSERVATION_CHARS = 2000
# 工具 Schema 文本注入上限（每条定义压缩后拼入系统指令）
_MAX_TOOL_SCHEMA_CHARS = 900
# 计划步数缺省上限（LLM 版 slots.steps 缺失时的保守兜底，非静默钳制来源）
_DEFAULT_MAX_STEPS = 7

_PLAN_SYSTEM = (
    "你是评测平台对话引擎的规划器。只输出一个 JSON 对象，不要输出任何其他文字。\n"
    '格式：{"intent":"一句话意图","skill_id":null或技能ID,"slots":{"steps":'
    '["第1步",...3到7步],其他槽位},"tools_needed":["只读短工具名"],'
    '"delivery":"chat","budget":{"model_calls":12,"tool_turns":8},'
    '"allows_replan":false,"notes":"不超过40字说明",'
    '"protocol":"plan","version":"plan.v1"}\n'
    "要求：步骤必须 3–7 步；tools_needed 只列短工具；探索任务 delivery=chat。"
)

# react.v1 输出说明：done 时在 JSON 之后附最终答复正文（JSON 前后文字被容忍）。
# 模板不含花括号示例（避免 str.format 冲突），协议 JSON 以字段文字描述。
_REACT_SYSTEM_TEMPLATE = (
    "你是评测平台对话引擎的执行器。每一轮只输出一个 JSON 对象，字段如下：\n"
    "thought：字符串，本轮动作摘要不超过 30 字；"
    "tool：工具名或 null；arguments：对象，工具参数；"
    "done：布尔；protocol 恒为 react；version 恒为 react.v1。\n"
    "规则：\n"
    "- 需要工具就输出 tool/arguments；完成探索后输出 done=true 且 tool=null；\n"
    "- done=true 时，请在 JSON 对象之后另起一行直接输出给用户的最终答复正文；\n"
    "- 只能用下列工具（JSON Schema 见上），不能编造工具名；\n"
    "- 已经重复读取过同一文件/检索过同一内容时，直接结束，不要重复调用。\n"
    "可用工具：\n{tool_schemas}"
)

# 确定性能力映射（intent → capabilities；与架构 ADR-3 / AgentDef 声明对齐）
_DIAGNOSE_CAPABILITIES = frozenset({"read_workspace", "analyze_report", "trace_task"})
_DATASET_CAPABILITIES = frozenset({"inspect_dataset", "prepare_slots"})
_DIAGNOSE_KEYWORDS = ("排查", "诊断", "定位", "分析", "查", "原因", "为什么", "报告", "失败", "异常")
_DATASET_KEYWORDS = ("数据集", "数据", "槽位", "检视", "整理", "清单")

# 只读工具（OR-4 重复守卫对象；与 ToolRegistry risk_level="read" 一致的保守子集）
_READ_TOOLS: frozenset[str] = frozenset({"read", "web_search", "web_fetch", "TaskGet", "TaskList"})

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _latest_user_text(serializable: SerializableRequest) -> str:
    """提取本轮最后一条用户消息文本（与 router / workflow 节点同口径）。"""
    for message in reversed(list(serializable.get("messages") or ())):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _step(name: str) -> dict:
    return {"workflow_step": name}  # workflow_step 复用为 DAG 观测字段（engine=agent 亦记录）


def _capabilities_from_intent(intent: str) -> frozenset[str]:
    """plan.intent → 能力请求（确定性词表；空 = 回落 worker.general）。"""
    caps: set[str] = set()
    if any(keyword in intent for keyword in _DIAGNOSE_KEYWORDS):
        caps.update(_DIAGNOSE_CAPABILITIES)
    if any(keyword in intent for keyword in _DATASET_KEYWORDS):
        caps.update(_DATASET_CAPABILITIES)
    return frozenset(caps)


def _tool_schemas_text(tool_registry: object, allowed_tools: tuple[str, ...]) -> str:
    """allowed_tools 的定义文本（压缩 JSON Schema；未注册项跳过并由注册侧兜底）。"""
    lines: list[str] = []
    for name in allowed_tools:
        definition = tool_registry.find(name)  # type: ignore[attr-defined]
        if definition is None:
            continue
        try:
            schema = json.dumps(definition.input_schema, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            schema = "{}"
        if len(schema) > _MAX_TOOL_SCHEMA_CHARS:
            schema = schema[:_MAX_TOOL_SCHEMA_CHARS] + "…"
        lines.append(f"- {name}：{getattr(definition, 'description', '')}\n{schema}")
    return "\n".join(lines)


def _model_input(
    state: GraphState,
    *,
    system: str,
    extra_messages: list[Mapping[str, object]] | None = None,
) -> tuple[ModelRequest, dict]:
    """按会话协议档组装 ModelRequest（api_key 即时注入，不入 State）。"""
    serializable: SerializableRequest = state["request"]
    try:
        run_config = get_config()
    except RuntimeError:  # 图外直接调用（单测）无 run 上下文
        run_config = None
    configurable = (run_config or {}).get("configurable") or {}
    api_key = str(configurable.get("credentials", {}).get("api_key") or "")
    model_config = rebuild_model_config(serializable, api_key=api_key)
    messages: list[Mapping[str, object]] = [
        dict(message) for message in (serializable.get("messages") or ())
    ]
    if extra_messages:
        messages.extend(extra_messages)
    request = ModelRequest(config=model_config, messages=tuple(messages), system=system)  # type: ignore[arg-type]
    return request, configurable


def _observation_lines(state: GraphState) -> list[str]:
    """取最近若干条 Observation 文本（注入模型输入；Observation 只作模型输入）。"""
    observations = list(state.get("observations") or [])
    lines: list[str] = []
    for observation in observations[-_MAX_INJECTED_OBSERVATIONS:]:
        if not isinstance(observation, Mapping):
            continue
        tool = str(observation.get("tool") or "")
        text = str(observation.get("text") or "")
        if len(text) > _MAX_OBSERVATION_CHARS:
            text = text[:_MAX_OBSERVATION_CHARS] + "…"
        ok = "成功" if observation.get("ok") else "失败"
        lines.append(f"[工具 {tool} 执行{ok}]\n{text}")
    return lines


def _repeat_count(state: GraphState, name: str, arguments: Mapping[str, object]) -> int:
    """同参调用历史计数（OR-4：全历史统计，规范化 JSON 比对）。"""
    signature = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    count = 0
    for observation in state.get("observations") or []:
        if not isinstance(observation, Mapping):
            continue
        if observation.get("tool") != name:
            continue
        obs_args = observation.get("arguments")
        if isinstance(obs_args, Mapping):
            if json.dumps(obs_args, sort_keys=True, ensure_ascii=False) == signature:
                count += 1
        elif obs_args is None and not arguments:
            count += 1
    return count


def _redact_arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    """ToolCard 摘要脱敏：值截断、路径取末段、超长对象折叠（不留敏感全文）。"""
    redacted: dict[str, object] = {}
    for key, value in arguments.items():
        if isinstance(value, bool) or value is None or isinstance(value, int | float):
            redacted[key] = value
        elif isinstance(value, str):
            if len(value) > 60:
                redacted[key] = value[:60] + "…"
            elif "\\" in value or "/" in value:
                redacted[key] = value.replace("\\", "/").split("/")[-1]
            else:
                redacted[key] = value
        elif isinstance(value, list | tuple):
            redacted[key] = f"[{len(value)} 项]"
        else:
            redacted[key] = "<折叠>"
    return redacted


def _stray_reply_text(raw: str) -> str:
    """取 react JSON 之外的正文（JSON 之前/之后的说明文字；无则空串）。"""
    match = _JSON_RE.search(raw)
    if not match:
        return raw.strip()
    head = raw[: match.start()].strip()
    tail = raw[match.end() :].strip()
    return (tail or head).strip()


def _error_payload(code: str, message: str) -> list[dict]:
    return [make_event("error", {"code": code, "message": message})]


# ── plan 节点：一次模型调用出 plan.v1；失败降级 build_plan L0 ──


def make_plan_node(gateway: object):
    """构造 plan 节点（闭包绑定网关；节点签名只接收 state）。"""

    def node(state: GraphState) -> dict:
        if state.get("workflow_failed") or state.get("turn_failed"):
            return _step("plan")
        text = _latest_user_text(state["request"])
        request, _configurable = _model_input(
            state,
            system=_PLAN_SYSTEM + "\n\n用户请求：" + text,
        )
        plan: PlanArtifact
        try:
            response = gateway.invoke(request)  # type: ignore[attr-defined]
        except AppError as exc:
            plan = plan_lib.build_plan(text, fail_reason=str(exc))  # L0 降级
        else:
            try:
                fields = parse_plan_protocol(response.text)["fields"]
                payload = {key: value for key, value in fields.items() if key not in ("protocol", "version")}
                plan = validate_plan_artifact(payload)
                # 步骤数 3–7（S2）：越界视同解析失败走 L0 降级，不静默钳制
                slots = plan.slots if isinstance(plan.slots, Mapping) else {}
                steps = slots.get("steps")
                if isinstance(steps, list) and not 3 <= len(steps) <= 7:
                    plan = plan_lib.build_plan(text, fail_reason="步骤数越界")
            except AppError:
                plan = plan_lib.build_plan(text, fail_reason="协议解析失败")  # L0 降级
        budget = plan_lib.budget_for_plan(plan).to_dict()
        return {
            **_step("plan"),
            "plan": to_dict(plan),
            "plan_step_index": 0,
            "budget": budget,
        }

    return node


# ── discover 节点：确定性选 Worker + 收窄 allowed_tools（零模型调用）──


def make_discover_node(agent_registry: object, tool_registry: object):
    """构造 discover 节点；视野任何一项未注册即 fail-fast 就地收尾。"""

    def node(state: GraphState) -> dict:
        if state.get("workflow_failed") or state.get("turn_failed"):
            return _step("discover")
        plan = state.get("plan")
        intent = str((plan or {}).get("intent") or "") if isinstance(plan, Mapping) else ""
        skill_id = plan.get("skill_id") if isinstance(plan, Mapping) else None
        capabilities = _capabilities_from_intent(intent)
        try:
            definition = agent_registry.discover(  # type: ignore[attr-defined]
                capabilities=capabilities,
                skill_id=str(skill_id) if skill_id else None,
            )
        except AppError as exc:
            return {
                **_step("discover"),
                "turn_failed": True,
                "pending_events": _error_payload(exc.code.value, str(exc)),
            }
        allowed = tuple(definition.allowed_tools)
        unknown = [name for name in allowed if not tool_registry.is_registered(name)]  # type: ignore[attr-defined]
        if unknown:
            return {
                **_step("discover"),
                "turn_failed": True,
                "pending_events": _error_payload(
                    "VALIDATION", f"Worker 视野含未注册工具：{', '.join(unknown)}"
                ),
            }
        return {**_step("discover"), "agent_id": definition.agent_id, "allowed_tools": allowed}

    return node


# ── orchestrator 节点【哑】：Observe → Think → Act ──


def make_orchestrator_node(gateway: object, agent_registry: object, tool_registry: object):
    """构造 TAOR 循环节点（读观察 → 调模型 → 产 Act 或收尾；不 rewrite 意图）。"""

    def _max_steps(state: GraphState) -> int:
        slots = (state.get("plan") or {}).get("slots") if isinstance(state.get("plan"), Mapping) else None
        steps = slots.get("steps") if isinstance(slots, Mapping) else None
        if isinstance(steps, list) and steps:
            return len(steps)
        return _DEFAULT_MAX_STEPS

    def node(state: GraphState) -> dict:
        if state.get("turn_failed"):
            return _step("orchestrator")
        budget = from_dict(state.get("budget") or {})
        if is_budget_exhausted(budget):
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "pending_events": _error_payload("BUDGET_EXCEEDED", "模型调用预算耗尽"),
            }
        agent_id = str(state.get("agent_id") or "")
        definition = agent_registry.find(agent_id)  # type: ignore[attr-defined]
        allowed_tools = tuple(state.get("allowed_tools") or ())
        if definition is None or not allowed_tools:
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "pending_events": _error_payload("VALIDATION", "Worker 视野缺失，无法执行"),
            }
        # 越界守卫：Act 已在计划步数外 → 直接 turn_failed（不静默钳制）
        index = int(state.get("plan_step_index") or 0)
        if index > _max_steps(state):
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "pending_events": _error_payload("INTERNAL", "计划步数越界，结束本轮"),
            }
        observation_lines = _observation_lines(state)
        system = _REACT_SYSTEM_TEMPLATE.format(
            tool_schemas=_tool_schemas_text(tool_registry, allowed_tools)
        )
        extra: list[Mapping[str, object]] = []
        if observation_lines:
            extra.append(
                {
                    "role": "user",
                    "content": "上一步工具观察：\n" + "\n".join(observation_lines),
                }
            )
        raw: str = ""
        attempts = 0
        max_attempts = 2  # parse_retries ≤ 2（含首次共 3 次尝试的上限语义：首次 + 2 重试）
        while attempts <= max_attempts:
            request, _configurable = _model_input(state, system=system, extra_messages=extra)
            try:
                response = gateway.invoke(request)  # type: ignore[attr-defined]
            except AppError as exc:
                budget = consume_model_call(budget)
                attempts += 1
                if attempts > max_attempts:
                    return {
                        **_step("orchestrator"),
                        "turn_failed": True,
                        "budget": budget.to_dict(),
                        "pending_events": _error_payload(
                            exc.code.value, "执行模型连续失败，结束本轮"
                        ),
                    }
                continue
            budget = consume_model_call(budget)
            raw = response.text
            try:
                fields = parse_react(raw)["fields"]
                break
            except AppError:
                attempts += 1
                extra = [
                    {
                        "role": "user",
                        "content": "上一轮输出不是合法的 react.v1 JSON，请只输出 JSON 对象。",
                    }
                ]
                if attempts > max_attempts:
                    return {
                        **_step("orchestrator"),
                        "turn_failed": True,
                        "budget": budget.to_dict(),
                        "pending_events": _error_payload(
                            "VALIDATION", "执行协议解析连续失败，结束本轮"
                        ),
                    }
        else:
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "budget": budget.to_dict(),
                "pending_events": _error_payload("VALIDATION", "执行协议解析失败，结束本轮"),
            }

        tool_name = fields.get("tool")
        done = bool(fields.get("done"))
        if done or not tool_name:
            text = _stray_reply_text(raw) or f"已完成：{_intent_text(state)}"
            engine = state.get("engine")
            completed: dict[str, object] = {
                "finish_reason": "stop",
                "role": "assistant",
                "engine": engine,
                "agent_id": agent_id,
            }
            if engine is not None:
                completed["router_confidence"] = state.get("router_confidence")
                completed["router_reason"] = state.get("router_reason")
            return {
                **_step("orchestrator"),
                "budget": budget.to_dict(),
                "pending_events": [
                    make_event("assistant_message", {"text": text, "role": "assistant", "latency_ms": 0}),
                    make_event("response.completed", completed),
                ],
                "response": {"text": text, "usage": {}, "latency_ms": 0},
            }

        name = str(tool_name)
        if name not in allowed_tools or not tool_registry.is_registered(name):  # type: ignore[attr-defined]
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "budget": budget.to_dict(),
                "pending_events": _error_payload(
                    "VALIDATION", f"非法工具调用：{name}（不在本轮视野内）"
                ),
            }
        arguments = dict(fields.get("arguments") or {})
        if name in _READ_TOOLS and _repeat_count(state, name, arguments) >= 3:
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "budget": budget.to_dict(),
                "pending_events": _error_payload(
                    "VALIDATION", f"重复读取已守卫：{name} 同一参数已执行 3 次"
                ),
            }
        call_id = f"toolcall_{uuid.uuid4().hex}"
        return {
            **_step("orchestrator"),
            "plan_step_index": index + 1,
            "budget": budget.to_dict(),
            "pending_tool": {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "native": True,
            },
            "pending_events": [
                make_event(
                    "tool_call",
                    {
                        "call_id": call_id,
                        "name": name,
                        "arguments": _redact_arguments(arguments),
                    },
                )
            ],
        }

    return node


def _intent_text(state: GraphState) -> str:
    plan = state.get("plan")
    if isinstance(plan, Mapping):
        return str(plan.get("intent") or "任务")
    return "任务"


# ── tools 节点【哑】：复用 toolnode 十层链 + 预算/耗尽守卫 ──


def make_tools_node(tool_node: object):
    """包装 ``toolnode.build_tool_node`` 产物：执行后按观察数扣 tool_turns。"""

    async def node(state: GraphState) -> dict:
        if not state.get("pending_tool"):
            return {"pending_events": []}
        result: dict[str, Any] = dict(await tool_node(state))  # type: ignore[misc]
        observed = result.get("observations")
        count = len(observed) if isinstance(observed, list) else 0
        if count:
            # 逐次消费 tool_turns；超限抛 BUDGET_EXCEEDED → 扣到 0 即停，
            # 由 orchestrator 前置检查收尾（不静默，也不在节点内改写语义）。
            budget = from_dict(state.get("budget") or {})
            for _ in range(count):
                try:
                    budget = consume_tool_turn(budget)
                except AppError:
                    break
            result["budget"] = budget.to_dict()
            result = seal_budget_if_exhausted(
                result, {**state, "budget": budget.to_dict()}
            )
        return result

    return node
