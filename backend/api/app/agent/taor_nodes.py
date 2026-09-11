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

import logging
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from langgraph.config import get_config

from app.errors import AppError
from app.harness.context.assembly import select_tool_defs
from app.harness.contracts import Observation, PlanArtifact, make_event, to_dict
from app.harness.contracts.artifacts import validate_plan_artifact
from app.harness.execution.native_results import runtime_thread_id
from app.harness.execution.native_tools_policy import (
    native_tools_allowed,
    native_tools_report_failure,
    native_tools_report_success,
)
from app.harness.execution.stream_policy import profile_id_from_configurable
from app.harness.execution.toolnode import seal_budget_if_exhausted
from app.harness.feedback.review import MAX_REPAIRS, MAX_REPLANS, review
from app.harness.memory import GraphState
from app.harness.orchestration import plan as plan_lib
from app.harness.orchestration.budget import (
    consume_model_call,
    consume_tool_turn,
    from_dict,
    is_budget_exhausted,
)
from app.harness.prompts.protocols import parse_plan_protocol, parse_react, parse_reflect

from .taor_support import (
    _DEFAULT_CLARIFY_QUESTION,
    _DEFAULT_MAX_STEPS,
    _FABRICATION_CLAIM_PATTERNS,
    _FABRICATION_REPAIR_HINT,
    _MAX_OBSERVATION_CHARS,
    _MAX_REPLAN_REASON_CHARS,
    _PLAN_SYSTEM,
    _REACT_NATIVE_SYSTEM,
    _REACT_SYSTEM_TEMPLATE,
    _READ_TOOLS,
    _REFLECT_SYSTEM,
    _build_native_backfill,
    _capabilities_from_intent,
    _completed_payload,
    _error_payload,
    _failure_reason,
    _last_observation,
    _latest_user_text,
    _merge_usage,
    _model_input,
    _observation_lines,
    _plan_artifact,
    _redact_arguments,
    _repeat_count,
    _step,
    _stray_reply_text,
    _terminal_events,
    _tool_schemas_text,
)

logger = logging.getLogger("ai-eval.agent")


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
        usage_acc = _merge_usage(state.get("turn_usage"), None)
        try:
            response = gateway.invoke(request)  # type: ignore[attr-defined]
        except AppError as exc:
            plan = plan_lib.build_plan(text, fail_reason=str(exc))  # L0 降级
        else:
            usage_acc = _merge_usage(usage_acc, response.usage)
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
            "turn_usage": usage_acc,
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


def make_orchestrator_node(
    gateway: object,
    agent_registry: object,
    tool_registry: object,
    native_tool_results: object | None = None,
):
    """构造 TAOR 循环节点（读观察 → 调模型 → 产 Act 或收尾；不 rewrite 意图）。

    F0/P2：``native_tool_results``（NativeToolResultStore 实例）由图接线注入
    （与 build_tool_node 同源）；缺失时原生循环不可用，tool_use 响应回退文本
    协议（fail-safe，P1 语义保留）。
    """

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
        # F0/P2：原生循环（方案 V0.2 D1/D3，仅 orchestrator 执行轮；plan/reflect
        # 不装配）。Observe：上一原生轮 tools 执行完毕（pending_tool 清空）后，
        # 从 native_tool_round + NativeToolResultStore 合成 assistant+tool 回填对
        # 注入下一轮请求（正文缺失时显式降级文案）。Act：tool_use → 名守卫 →
        # 全量入队（native=True，tools 节点自环 drain）→ 新 round 缓冲。
        # 关闸/未接线（store 缺失）时保持文本路径（P1 语义，fail-safe）。
        try:
            run_config = get_config()
        except RuntimeError:  # 图外直接调用（单测）无 run 上下文
            run_config = None
        configurable = (run_config or {}).get("configurable") or {}
        profile_id = profile_id_from_configurable(configurable)
        native_mode = native_tools_allowed(profile_id)
        thread_id = runtime_thread_id(configurable)
        native_cycle = bool(native_mode and native_tool_results is not None and thread_id)
        native_defs: tuple[Mapping[str, object], ...] = (
            tuple(select_tool_defs(tool_registry, mode="react", only=allowed_tools))  # type: ignore[arg-type]
            if native_mode
            else ()
        )
        legacy_system = _REACT_SYSTEM_TEMPLATE.format(
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
        # 消费上一原生轮（tools 已执行完毕回到本节点时）→ 回填对追加在消息
        # 最末（role=tool 段尾随 assistant 段，满足 anthropic 紧邻约束）
        native_round = state.get("native_tool_round")
        round_out: Mapping[str, object] | None = None
        if (
            native_cycle
            and isinstance(native_round, Mapping)
            and not state.get("pending_tool")
        ):
            backfill = _build_native_backfill(native_round, native_tool_results, thread_id)
            if backfill:
                extra.extend(backfill)
        raw: str = ""
        attempts = 0
        max_attempts = 2  # parse_retries ≤ 2（含首次共 3 次尝试的上限语义：首次 + 2 重试）
        usage_acc = _merge_usage(state.get("turn_usage"), None)
        while attempts <= max_attempts:
            request, _configurable = _model_input(
                state,
                system=_REACT_NATIVE_SYSTEM if native_mode else legacy_system,
                extra_messages=extra,
                tools=native_defs if native_mode else (),
            )
            try:
                response = gateway.invoke(request)  # type: ignore[attr-defined]
            except AppError as exc:
                if native_mode:
                    # 档级熔断：带 tools 请求失败（含端点 400/超时等）→ 计数，达阈值摘除
                    native_tools_report_failure(profile_id)
                budget = consume_model_call(budget)
                attempts += 1
                if attempts > max_attempts:
                    return {
                        **_step("orchestrator"),
                        "turn_failed": True,
                        "budget": budget.to_dict(),
                        "turn_usage": usage_acc,
                        "native_tool_round": round_out,
                        "pending_events": _error_payload(
                            exc.code.value, "执行模型连续失败，结束本轮"
                        ),
                    }
                continue
            budget = consume_model_call(budget)
            usage_acc = _merge_usage(usage_acc, response.usage)
            if native_mode:
                native_tools_report_success(profile_id)
            if native_mode and not native_cycle and response.tool_calls:
                # fail-safe（P1 语义保留）：装配开启但原生循环未接线（store 缺失
                # /图外直测）→ tool_use 以无 tools 请求重发一次并记审计；本回合
                # 后续转文本协议（防摇摆双执行）。P2 正式图均接 store，不走此支。
                names = ",".join(str(tool.name) for tool in response.tool_calls)
                logger.info(
                    "native_tools_defer profile=%s tools=%s（原生循环未接线，回退文本协议）",
                    profile_id,
                    names,
                )
                native_mode = False
                extra = [
                    {
                        "role": "user",
                        "content": "本轮工具定义已移除，请按文本协议输出 react.v1 JSON"
                        "（tool/arguments/done），不要输出任何其他文字。",
                    }
                ]
                continue  # tool_use 非解析失败，不递增 attempts（模型调用预算已扣）
            if native_cycle and response.tool_calls:
                # P2 原生 Act（D3）：逐 tool_use 名守卫（∉ allowed/未注册 →
                # VALIDATION 就地收尾，语义与文本 L559 一致）；同参重复守卫沿用
                # OR-4；通过后全量入队 pending_tool/pending_tools（native=True，
                # tools 节点自环逐个执行），assistant 段 + 调用清单写 round 缓冲。
                pending_items: list[Mapping[str, object]] = []
                round_calls: list[Mapping[str, object]] = []
                call_events: list[dict] = []
                for tool_call in response.tool_calls:
                    call_name = str(getattr(tool_call, "name", "") or "")
                    call_args = dict(getattr(tool_call, "arguments", None) or {})
                    if (
                        not call_name
                        or call_name not in allowed_tools
                        or not tool_registry.is_registered(call_name)  # type: ignore[attr-defined]
                    ):
                        return {
                            **_step("orchestrator"),
                            "turn_failed": True,
                            "budget": budget.to_dict(),
                            "turn_usage": usage_acc,
                            "native_tool_round": round_out,
                            "pending_events": _error_payload(
                                "VALIDATION",
                                f"非法工具调用：{call_name}（不在本轮视野内）。"
                                "如需读取/整理文件或运行脚本等执行类能力，请在请求中明确说明用途"
                                "（如『运行脚本…』），Agent 将按声明能力重新路由；不要尝试越权调用。",
                            ),
                        }
                    if call_name in _READ_TOOLS and _repeat_count(state, call_name, call_args) >= 3:
                        return {
                            **_step("orchestrator"),
                            "turn_failed": True,
                            "budget": budget.to_dict(),
                            "turn_usage": usage_acc,
                            "native_tool_round": round_out,
                            "pending_events": _error_payload(
                                "VALIDATION", f"重复读取已守卫：{call_name} 同一参数已执行 3 次"
                            ),
                        }
                    call_id = str(getattr(tool_call, "call_id", "") or "") or f"toolcall_{uuid.uuid4().hex}"
                    pending_items.append(
                        {
                            "call_id": call_id,
                            "name": call_name,
                            "arguments": call_args,
                            "native": True,
                        }
                    )
                    round_calls.append(
                        {"call_id": call_id, "name": call_name, "arguments": call_args}
                    )
                    call_events.append(
                        make_event(
                            "tool_call",
                            {
                                "call_id": call_id,
                                "name": call_name,
                                "arguments": _redact_arguments(call_args),
                            },
                        )
                    )
                stray_text = str(response.text or "").strip()
                if len(stray_text) > _MAX_OBSERVATION_CHARS:
                    stray_text = stray_text[:_MAX_OBSERVATION_CHARS] + "…"
                round_out = {
                    "assistant": {
                        "role": "assistant",
                        "content": stray_text,
                        "tool_calls": list(round_calls),
                    }
                }
                return {
                    **_step("orchestrator"),
                    "plan_step_index": index + 1,
                    "budget": budget.to_dict(),
                    "turn_usage": usage_acc,
                    "native_tool_round": round_out,
                    "pending_tool": pending_items[0],
                    "pending_tools": pending_items[1:],
                    "pending_events": call_events,
                }
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
                        "turn_usage": usage_acc,
                        "native_tool_round": round_out,
                        "pending_events": _error_payload(
                            "VALIDATION", "执行协议解析连续失败，结束本轮"
                        ),
                    }
        else:
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
                "native_tool_round": round_out,
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
                "turn_usage": usage_acc,
                "native_tool_round": round_out,
                "final_text": text,
                "response": {"text": text, "usage": usage_acc, "latency_ms": 0},
            }

        name = str(tool_name)
        if name not in allowed_tools or not tool_registry.is_registered(name):  # type: ignore[attr-defined]
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
                "native_tool_round": round_out,
                "pending_events": _error_payload(
                    "VALIDATION",
                    f"非法工具调用：{name}（不在本轮视野内）。"
                    "如需读取/整理文件或运行脚本等执行类能力，请在请求中明确说明用途"
                    "（如『运行脚本…』），Agent 将按声明能力重新路由；不要尝试越权调用。",
                ),
            }
        arguments = dict(fields.get("arguments") or {})
        if name in _READ_TOOLS and _repeat_count(state, name, arguments) >= 3:
            return {
                **_step("orchestrator"),
                "turn_failed": True,
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
                "native_tool_round": round_out,
                "pending_events": _error_payload(
                    "VALIDATION", f"重复读取已守卫：{name} 同一参数已执行 3 次"
                ),
            }
        call_id = f"toolcall_{uuid.uuid4().hex}"
        return {
            **_step("orchestrator"),
            "plan_step_index": index + 1,
            "budget": budget.to_dict(),
            "turn_usage": usage_acc,
            "native_tool_round": round_out,
            "pending_tool": {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                # 文本路径（F0/P2 前 legacy 语义）：观察经 _observation_lines 注入；
                # native=False → toolnode 不写 store、产正常 Observation 回灌。
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
            # F5/G6（MAJ-9②）：升档中间帧（拒写 denied，escalation=True）是过程
            # 事实而非终态失败——批准重放后末帧可能成功，按事件序收敛判定，
            # 该帧不计入连续失败（否则成功升档回合被误判进 repair 阶梯）。
            final_frames = [
                (event.get("payload") or {})
                for event in result.get("pending_events") or []
                if isinstance(event, Mapping) and event.get("kind") == "tool_result"
                and not (event.get("payload") or {}).get("escalation")
            ]
            rejected = any(frame.get("ok") is False for frame in final_frames)
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


def _fabrication_claim(state: GraphState) -> str | None:
    """收尾答复文本中的无证据声明检测（P3/R3-M6 窄版，零模型）。

    命中 = 声明了「本回合即时动作」类平台操作（发送确认卡/创建入队任务），
    但本回合无对应工具的成功执行记录（observations ok=True 且 tool ∈ 证据集）。
    返回命中类别文案；未命中返回 None。
    """
    text = str(state.get("final_text") or "").strip()
    if not text:
        return None
    evidence: set[str] = set()
    for observation in state.get("observations") or []:
        if isinstance(observation, Mapping) and observation.get("ok"):
            evidence.add(str(observation.get("tool") or ""))
    for label, pattern, tools in _FABRICATION_CLAIM_PATTERNS:
        if pattern.search(text) and not (evidence & tools):
            return label
    return None


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

    def _l3_fields(
        state: GraphState,
    ) -> tuple[dict[str, object] | None, Mapping[str, object]]:
        """一次受控复核短调用；失败/非法 fields 返回 None（调用方按「无结论」处理）。

        F0/P1：同时返回该次调用的 usage（回合累计审计来源）；异常/非法路径为空。
        """
        usage: Mapping[str, object] = {}
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
            return None, usage
        usage = response.usage
        try:
            return dict(parse_reflect(response.text)["fields"]), usage
        except AppError:
            return None, usage

    def node(state: GraphState) -> dict:
        base = _step("reflect")
        budget = from_dict(state.get("budget") or {})
        usage_acc = _merge_usage(state.get("turn_usage"), None)
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
                "turn_usage": usage_acc,
                "pending_events": [
                    make_event("response.completed", _completed_payload(state, "error"))
                ],
                "response": {"text": "", "usage": usage_acc, "latency_ms": 0},
            }
        plan = _plan_artifact(state)
        if plan is None:
            # 计划投影缺失：无判决依据，按硬错误收尾（不猜、不静默放行）
            return {
                **base,
                "verdict": "reject",
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
                "pending_events": _terminal_events(
                    state, "本轮计划缺失，已停止执行。", "error"
                ),
                "response": {"text": "", "usage": usage_acc, "latency_ms": 0},
            }

        # ── L1.5（P3，R3-M6）：编造对账——收尾声明无本回合工具证据 → 修复/
        # 拒绝（零模型硬护栏）。修复配额与 L2 共用（防无限循环）；纠正观察以
        # ok=False 回灌（review 以 step_fail_count 判定失败，本观察不误触阶梯）。
        fabrication = _fabrication_claim(state)
        if fabrication:
            if repair_count < MAX_REPAIRS:
                return {
                    **base,
                    "verdict": "repair",
                    "budget": budget.to_dict(),
                    "turn_usage": usage_acc,
                    "repair_count": repair_count + 1,
                    "observations": [
                        to_dict(
                            Observation(
                                tool="reflect",
                                text=_FABRICATION_REPAIR_HINT.format(claim=fabrication),
                                ok=False,
                                source="reflect",
                            )
                        )
                    ],
                }
            text = (
                f"本轮未能完成：检测到未证实声明「{fabrication}」，提示修正后仍复现"
                "（平台禁止声称未实际执行的确认卡/任务操作）。"
            )
            return {
                **base,
                "verdict": "reject",
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
                "pending_events": [
                    make_event(
                        "fabrication",
                        {"claim": fabrication, "repairs": int(repair_count)},
                    ),
                    *_terminal_events(state, text, "error"),
                ],
                "response": {"text": "", "usage": usage_acc, "latency_ms": 0},
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
            l3, l3_usage = _l3_fields(state)
            usage_acc = _merge_usage(usage_acc, l3_usage)
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
                "turn_usage": usage_acc,
                # 修复配额为回合级：消费后不再归还，成功也不重置（防无限修复）
                "repair_count": repair_count + 1,
                "observations": [_repair_observation(state, fields)],
            }
        if verdict == "retry":
            return {
                **base,
                "verdict": "retry",
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
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
                "turn_usage": usage_acc,
                "pending_events": _terminal_events(state, text, "stop"),
                "response": {"text": text, "usage": usage_acc, "latency_ms": 0},
            }
        if verdict == "reject":
            text = _reject_message(state, reason)
            return {
                **base,
                "verdict": "reject",
                "budget": budget.to_dict(),
                "turn_usage": usage_acc,
                "pending_events": _terminal_events(state, text, "error"),
                "response": {"text": text, "usage": usage_acc, "latency_ms": 0},
            }
        # pass：回显 orchestrator 的候选答复并正常收尾
        text = str(state.get("final_text") or "").strip() or f"已完成：{_intent_text(state)}"
        return {
            **base,
            "verdict": "pass",
            "budget": budget.to_dict(),
            "turn_usage": usage_acc,
            "pending_events": _terminal_events(state, text, "stop"),
            "response": {"text": text, "usage": usage_acc, "latency_ms": 0},
        }

    return node
