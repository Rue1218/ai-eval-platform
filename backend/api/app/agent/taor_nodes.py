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
  门禁 → 权限 → 并发 → 脱敏），结果回灌 Observation（只作模型输入）；
  顺带维护 ``step_fail_count``（同一步连续工具失败数，驱动 H4 失败阶梯）。

H4：**orchestrator 收尾移交 ``reflect``**——模型自主停止或守卫截断时不再直接
发 ``response.completed``，只把候选答复写入 ``final_text``，由 reflect 判决
后统一收尾（保证 ``reject`` 不会被先发出的 ``stop`` 覆盖）。

``reflect`` 节点（H4 五档判决，每次进入只出一个 verdict、**不自我重入**）：

- L1：``turn_failed``（硬错误）一律 ``reject``，任何路径不得产出 ``pass``；
- L2：工具失败阶梯 ``repair → retry → reject``（``MAX_REPAIRS=1`` /
  ``MAX_REPLANS=2``，常量唯一来源 ``feedback.review``）；
- L3：无失败时才做一次受控短调用（``reflect.v1``，计入预算），只可把 ``pass``
  降级为 ``clarify`` / ``reject``；预算耗尽或上游失败即跳过 L3。
- ``repair``：把 ``repair_hint`` 包成 Observation 回灌下一轮 Executor；
- ``retry``：置 ``force_replan`` + ``replan_reason`` 回 ``plan`` 重规划
  （``replan_reason`` 只进新 Plan 的 ``notes``，不参与技能关键词匹配）；
- ``pass`` / ``clarify`` / ``reject``：发 ``assistant_message`` +
  ``response.completed`` 收尾（``reject`` 的 ``finish_reason="error"``）。

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
from dataclasses import replace
from typing import Any

from langgraph.config import get_config

from app.errors import AppError
from app.harness.contracts import Observation, PlanArtifact, make_event, to_dict
from app.harness.contracts.artifacts import validate_plan_artifact
from app.harness.execution.toolnode import seal_budget_if_exhausted
from app.harness.feedback.review import MAX_REPAIRS, MAX_REPLANS, review
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
from app.harness.orchestration import plan as plan_lib
from app.harness.orchestration.budget import (
    consume_model_call,
    consume_tool_turn,
    from_dict,
    is_budget_exhausted,
)
from app.harness.prompts.protocols import parse_plan_protocol, parse_react, parse_reflect
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
# 重规划原因写回 PlanArtifact.notes 的截断长度（notes 是规划摘要，不是错误日志）
_MAX_REPLAN_REASON_CHARS = 200
# 澄清问句缺省文案（模型未给 clarify_question 时的可读兜底，不编造事实）
_DEFAULT_CLARIFY_QUESTION = "需要你补充一点信息才能继续，请说明具体目标或范围。"

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

# reflect.v1 输出说明（H4）：只在无工具失败时做一次受控核对，判决只能降级。
_REFLECT_SYSTEM = (
    "你是评测平台对话引擎的复核器。只输出一个 JSON 对象，不要输出任何其他文字。\n"
    '格式：{"verdict":"pass","reason":"不超过40字理由",'
    '"clarify_question":null或一句问句,"repair_hint":null或一句修复建议,'
    '"protocol":"reflect","version":"reflect.v1"}\n'
    "verdict 取值与含义：pass=候选答复可以直接给用户；"
    "clarify=信息不足，必须向用户提问（同时填 clarify_question）；"
    "reject=候选答复不可用且无法自动修复；"
    "repair=工具用法有误，填 repair_hint 给出可执行修复建议；"
    "retry=当前计划整体走不通，需要重新规划。\n"
    "规则：没有工具失败时不要输出 repair / retry；拿不准就 pass，不要过度质疑。\n"
)

# 确定性能力映射（intent → capabilities；与架构 ADR-3 / AgentDef 声明对齐）
_DIAGNOSE_CAPABILITIES = frozenset({"read_workspace", "analyze_report", "trace_task"})
_DATASET_CAPABILITIES = frozenset({"inspect_dataset", "prepare_slots"})
_DIAGNOSE_KEYWORDS = ("排查", "诊断", "定位", "分析", "查", "原因", "为什么", "报告", "失败", "异常")
_DATASET_KEYWORDS = ("数据集", "数据", "槽位", "检视", "整理", "清单")
# code 能力触发词（H5 收尾演练/未来放行通道）。注意双闸：即便意图命中这里，
# discover 的 worker.sandbox 静态排除仍常闭（agent_drill_sandbox_enabled 默认
# False）——带 run_script 的请求在生产零命中回落 worker.general，行为与词表
# 引入前等价（fail-closed），不会因此获得 bash。
_SANDBOX_CAPABILITIES = frozenset({"run_script", "verify_output"})
_SANDBOX_KEYWORDS = ("运行脚本", "执行命令", "跑脚本", "运行代码", "执行 bash", "跑一下代码")

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
    if any(keyword in intent for keyword in _SANDBOX_KEYWORDS):
        caps.update(_SANDBOX_CAPABILITIES)
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


def _completed_payload(state: GraphState, finish_reason: str) -> dict[str, object]:
    """构造 ``response.completed`` payload（H3 orchestrator 收尾同口径）。

    ``engine`` / ``router_confidence`` / ``router_reason`` 为 H1 审计三元组，
    仅混合引擎开启（engine 已写入）时出现，保证主开关关闭时 payload 不漂移。
    """
    engine = state.get("engine")
    payload: dict[str, object] = {
        "finish_reason": finish_reason,
        "role": "assistant",
        "engine": engine,
        "agent_id": state.get("agent_id"),
    }
    if engine is not None:
        payload["router_confidence"] = state.get("router_confidence")
        payload["router_reason"] = state.get("router_reason")
    return payload


def _terminal_events(state: GraphState, text: str, finish_reason: str) -> list[dict]:
    """收尾事件对：``assistant_message`` + ``response.completed``（后者必须最后一条）。"""
    return [
        make_event("assistant_message", {"text": text, "role": "assistant", "latency_ms": 0}),
        make_event("response.completed", _completed_payload(state, finish_reason)),
    ]


def _last_observation(state: GraphState) -> Observation | None:
    """取最近一条 Observation 对象；投影不匹配返回 None（不猜、不抛给浏览器）。"""
    observations = list(state.get("observations") or [])
    for item in reversed(observations):
        if not isinstance(item, Mapping):
            continue
        try:
            return Observation(**dict(item))  # type: ignore[arg-type]
        except TypeError:
            continue
    return None


def _plan_artifact(state: GraphState) -> PlanArtifact | None:
    """从 State 投影重建 PlanArtifact；字段不匹配返回 None（不猜、不静默放行）。"""
    plan = state.get("plan")
    if not isinstance(plan, Mapping):
        return None
    try:
        return validate_plan_artifact(dict(plan))
    except (ValueError, TypeError):
        return None


def _failure_reason(state: GraphState) -> str:
    """从最近一条失败 Observation 取可读原因（截断；不含异常原文与堆栈）。"""
    observation = _last_observation(state)
    if observation is not None and not observation.ok:
        text = str(observation.text or "").strip()
        if text:
            return text[:_MAX_REPLAN_REASON_CHARS]
    return "执行中断"


# ── plan 节点：一次模型调用出 plan.v1；失败降级 build_plan L0 ──


def make_plan_node(gateway: object):
    """构造 plan 节点（闭包绑定网关；节点签名只接收 state）。

    H4：``force_replan`` 为真时按 reflect 打回重规划——``replan_reason`` 只进
    系统指令与新 Plan 的 ``notes``，**绝不并入** ``build_plan`` 的文本入参
    （否则会参与 L0 技能关键词匹配，把失败文本误命中为技能）；游标与连续失败
    计数归零，预算**沿用剩余值**（换计划不放大回合预算）。
    """

    def node(state: GraphState) -> dict:
        if state.get("workflow_failed") or state.get("turn_failed"):
            return _step("plan")
        text = _latest_user_text(state["request"])
        force_replan = bool(state.get("force_replan"))
        replan_reason = str(state.get("replan_reason") or "") if force_replan else ""
        system = _PLAN_SYSTEM + "\n\n用户请求：" + text
        if replan_reason:
            system += "\n\n上次执行失败原因（仅供你调整步骤，不作为识别技能的依据）：" + replan_reason
        request, _configurable = _model_input(state, system=system)
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
        if replan_reason:
            plan = replace(
                plan,
                notes=f"{plan.notes}；上次执行失败：{replan_reason[:_MAX_REPLAN_REASON_CHARS]}",
            )
        budget_data = state.get("budget")
        if force_replan and isinstance(budget_data, Mapping) and budget_data:
            # 重规划沿用剩余预算：回合预算不因换计划而放大（防空转到耗尽）
            budget = dict(budget_data)
        else:
            budget = plan_lib.budget_for_plan(plan).to_dict()
        return {
            **_step("plan"),
            "plan": to_dict(plan),
            "plan_step_index": 0,
            "step_fail_count": 0,
            "verdict": None,
            "force_replan": False,
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
            # H4：收尾移交 reflect 判决——此处只落候选答复，不发 response.completed，
            # 否则 reflect 的 reject 会被先发出的 stop 覆盖（判决形同虚设）。
            text = _stray_reply_text(raw) or f"已完成：{_intent_text(state)}"
            return {
                **_step("orchestrator"),
                "budget": budget.to_dict(),
                "final_text": text,
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
                # H4 修正（H3 遗留缺陷）：本分支是**提示词驱动**的 ReAct 循环
                # ——观察经 _observation_lines 以用户消息注入下一轮模型输入，
                # 而非原生 tool 消息回填。置 native=True 会让 toolnode 把
                # observation 正文换成「已执行」占位并写入无人消费的
                # NativeToolResultStore（骨架化后 get() 零调用方），模型将永远
                # 看不到文件内容，失败阶梯也因 observations 缺失而失效。
                "native": False,
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
    """包装 ``toolnode.build_tool_node`` 产物：按观察数扣 tool_turns 并维护失败阶梯计数。

    H4：``step_fail_count`` 为「同一步连续工具失败数」，本步只要有一次失败就累加、
    全部成功即归零；reflect 的 L2 阶梯据此判定 ``repair`` / ``retry`` / ``reject``。
    """

    async def node(state: GraphState) -> dict:
        if not state.get("pending_tool"):
            return {"pending_events": []}
        result: dict[str, Any] = dict(await tool_node(state))  # type: ignore[misc]
        observed = result.get("observations")
        count = len(observed) if isinstance(observed, list) else 0
        if count:
            # 观察归一为纯 dict：toolnode 交回的是 Observation frozen dataclass，
            # 直接进 State 会让下游全部 Mapping 判定（观察注入 _observation_lines、
            # 防重复 _repeat_count、H4 失败阶梯）静默失效，且不可 json.dumps
            # ——H5 接 PgCheckpointer 后必然序列化失败。归一放在本包装层，
            # 不改动既有 toolnode 契约。
            normalized: list[object] = [
                to_dict(item) if hasattr(item, "__dataclass_fields__") else item
                for item in observed
            ]
            failed = sum(
                1 for item in normalized if isinstance(item, Mapping) and not item.get("ok")
            )
            result["observations"] = normalized
            result["step_fail_count"] = (
                int(state.get("step_fail_count") or 0) + failed if failed else 0
            )
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
        else:
            # 拒绝路径（门禁/权限/沙箱/未注册）不产 Observation，只发
            # tool_result(ok=false)；同样计入连续失败，否则失败阶梯看不见这类失败。
            rejected = any(
                isinstance(event, Mapping)
                and event.get("kind") == "tool_result"
                and (event.get("payload") or {}).get("ok") is False
                for event in result.get("pending_events") or []
            )
            if rejected:
                result["step_fail_count"] = int(state.get("step_fail_count") or 0) + 1
        return result

    return node


# ── reflect 节点（H4）：五档判决，每次进入只出一个 verdict，不自我重入 ──


def _repair_observation(state: GraphState, fields: Mapping[str, object]) -> dict:
    """把修复建议包成 Observation 回灌下一轮 Executor（只作模型输入，不落库）。

    优先用失败观察自带的 ``repair_hint``（工具链更懂失败原因），缺失时才用
    L3 模型给出的建议，最后退化为通用的「换工具/改参数」提示——三档都不得
    包含异常原文或堆栈。
    """
    failed = _last_observation(state)
    hint = str(getattr(failed, "repair_hint", "") or "").strip() if failed else ""
    if not hint:
        hint = str(fields.get("repair_hint") or "").strip()
    if not hint:
        hint = "上一次工具调用失败，请换用视野内允许的短工具或修正参数后重试。"
    return to_dict(Observation(tool="reflect", text=hint, ok=False, source="reflect"))


def _reject_message(state: GraphState, reason: str) -> str:
    """``reject`` 收尾文案：说明停在第几步与失败原因（可读，不泄漏堆栈）。"""
    index = int(state.get("plan_step_index") or 0)
    detail = reason or _failure_reason(state)
    return (
        f"本轮未能完成：已尝试修复最多 {MAX_REPAIRS} 次、重规划最多 {MAX_REPLANS} 次仍未通过，"
        f"停在第 {index} 步（{detail}）。"
    )


def make_reflect_node(gateway: object):
    """构造 reflect 节点（H4 Reflection 五档判决；闭包绑定网关）。

    判决顺序固定为 **L1 规则 → L2 阶梯 → L3 推理**，前级有结论即不再问后级：
    L1 的 ``reject`` 与 L2 的阶梯结论**永不被 L3 放行**（FB-3）。L3 仅在无失败时
    做一次受控短调用并计入预算；预算耗尽或上游失败即跳过 L3（不卡住用户）。
    """

    def _l3_fields(state: GraphState) -> dict[str, object] | None:
        """一次受控复核短调用；失败/非法返回 None（调用方按「无结论」处理）。"""
        text = str(state.get("final_text") or "")
        extra: list[Mapping[str, object]] = []
        if text:
            extra.append({"role": "user", "content": "候选最终答复：\n" + text})
        request, _configurable = _model_input(
            state, system=_REFLECT_SYSTEM, extra_messages=extra
        )
        try:
            response = gateway.invoke(request)  # type: ignore[attr-defined]
        except AppError:
            return None
        try:
            return dict(parse_reflect(response.text)["fields"])
        except AppError:
            return None

    def node(state: GraphState) -> dict:
        base = _step("reflect")
        budget = from_dict(state.get("budget") or {})
        step_fail_count = int(state.get("step_fail_count") or 0)
        repair_count = int(state.get("repair_count") or 0)
        replan_count = int(state.get("replan_count") or 0)

        # ── L1：硬错误一律 reject（任何路径不得产出 pass）──
        if state.get("turn_failed"):
            # 失败原因已由 orchestrator 的 error 事件下发，此处只补收尾帧，避免重复叙述
            return {
                **base,
                "verdict": "reject",
                "budget": budget.to_dict(),
                "pending_events": [
                    make_event("response.completed", _completed_payload(state, "error"))
                ],
                "response": {"text": "", "usage": {}, "latency_ms": 0},
            }
        plan = _plan_artifact(state)
        if plan is None:
            # 计划投影缺失：无判决依据，按硬错误收尾（不猜、不静默放行）
            return {
                **base,
                "verdict": "reject",
                "budget": budget.to_dict(),
                "pending_events": _terminal_events(
                    state, "本轮计划缺失，已停止执行。", "error"
                ),
                "response": {"text": "", "usage": {}, "latency_ms": 0},
            }

        # ── L2：确定性失败阶梯（review 库函数，零模型）──
        verdict = review(
            plan,
            _last_observation(state),
            step_fail_count=step_fail_count,
            repair_count=repair_count,
            replan_count=replan_count,
        )
        reason = ""
        fields: dict[str, object] = {}

        # ── L3：仅在无失败（判决为 pass）时核对一次，且只可降级不放行 ──
        if verdict == "pass" and not is_budget_exhausted(budget):
            budget = consume_model_call(budget)
            l3 = _l3_fields(state)
            if l3 is not None:
                fields = l3
                reason = str(l3.get("reason") or "")
                if l3.get("verdict") in ("clarify", "reject"):
                    verdict = str(l3["verdict"])

        # ── 硬上限兜底：即便前级已判，本节点再收一次口（防未来改动绕过）──
        if verdict == "repair" and repair_count >= MAX_REPAIRS:
            verdict = "reject"
        if verdict == "retry" and not (plan.allows_replan and replan_count < MAX_REPLANS):
            verdict = "reject"

        if verdict == "repair":
            return {
                **base,
                "verdict": "repair",
                "budget": budget.to_dict(),
                # 修复配额为回合级：消费后不再归还，成功也不重置（防无限修复）
                "repair_count": repair_count + 1,
                "observations": [_repair_observation(state, fields)],
            }
        if verdict == "retry":
            return {
                **base,
                "verdict": "retry",
                "budget": budget.to_dict(),
                "replan_count": replan_count + 1,
                "force_replan": True,
                "replan_reason": reason or _failure_reason(state),
                "plan_step_index": 0,
                "step_fail_count": 0,
            }
        if verdict == "clarify":
            question = str(fields.get("clarify_question") or "").strip()
            text = question or _DEFAULT_CLARIFY_QUESTION
            return {
                **base,
                "verdict": "clarify",
                "budget": budget.to_dict(),
                "pending_events": _terminal_events(state, text, "stop"),
                "response": {"text": text, "usage": {}, "latency_ms": 0},
            }
        if verdict == "reject":
            text = _reject_message(state, reason)
            return {
                **base,
                "verdict": "reject",
                "budget": budget.to_dict(),
                "pending_events": _terminal_events(state, text, "error"),
                "response": {"text": text, "usage": {}, "latency_ms": 0},
            }
        # pass：回显 orchestrator 的候选答复并正常收尾
        text = str(state.get("final_text") or "").strip() or f"已完成：{_intent_text(state)}"
        return {
            **base,
            "verdict": "pass",
            "budget": budget.to_dict(),
            "pending_events": _terminal_events(state, text, "stop"),
            "response": {"text": text, "usage": {}, "latency_ms": 0},
        }

    return node
