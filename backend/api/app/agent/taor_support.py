"""TAOR 节点支持层：常量与纯辅助（从 taor_nodes.py 拆出，2026-09-11）。

提供观察注入 / 回填预算常量、意图词表、模型输入装配、payload 构建与脱敏等
纯函数；节点工厂（``make_*_node``）保留在 ``taor_nodes.py``。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from langgraph.config import get_config

from app.harness.contracts import Observation, PlanArtifact, make_event
from app.harness.contracts.artifacts import validate_plan_artifact
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
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

# F0/P2：原生循环回填预算（方案 V0.2 R1-M4）——tool 正文经 store 合成注入时
# 单条二次裁剪上限（字符）并带截断标注（store 已按 600K 裁剪，此处防多轮
# 回填叠加撑爆 context 窗口；与流式/窗口预算同源精神，量级对齐 read 常用量）。
_MAX_BACKFILL_CHARS = 60_000
_BACKFILL_TRUNCATE_NOTICE = (
    "\n\n[注意：工具结果回填已截断，仅保留前 {limit} 字符——如需更多内容请用工具的分页/范围参数分次读取]"
)
# store 正文缺失降级文案（跨进程 resume / store 写入失败等；显式声明不可用，
# 禁止伪造正文——与平台禁编造纪律一致，R1-M5 降级决策）。
_NATIVE_BACKFILL_MISSING_TEXT = (
    "该工具已执行，但结果正文当前不可用（跨进程恢复或临时存储缺失）。"
    "如需内容请重新调用该工具，或按上一步观察继续。"
)
# toolnode 在 native 执行时写入观察的占位前缀（正文只进 store）——观察注入
# 模型输入时跳过该轮占位（正文已随 role=tool 回填，避免占位噪音双写）。
_NATIVE_OBSERVATION_PLACEHOLDER = "完整结果仅在当前回合供模型使用"

# F0/P3：编造对账（R3-M6 窄版，零模型）——收尾文本的声明-证据规则。窄集防
# 误报：仅覆盖「本回合即时动作」类声明（确认卡/任务创建入队），其证据必须为
# 本回合对应工具的成功执行（observations ok=True 且 tool ∈ 证据集）。文件/
# 搜索类声明不加规则（上下文含历史陈述，转述误报风险高，留观测日志）。
# 每条 = (类别文案, 声明正则, 证据工具集)。
_FABRICATION_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str], frozenset[str]], ...] = (
    (
        "向用户发送确认卡",
        re.compile(r"(?:已(?:向|经)?(?:发送|发出|发起)|发送了).{0,8}(?:确认卡|审批卡)|确认卡已(?:发送|发出)"),
        frozenset({"ask_user_question", "task", "TaskCreate"}),
    ),
    (
        "创建或入队评测任务",
        re.compile(r"已(?:创建|提交|入队)(?:评测)?任务|任务已(?:创建|提交|入队)"),
        frozenset({"task", "TaskCreate"}),
    ),
)
# 编造对账修复提示模板（注入观察回灌 Executor；与 L2 repair 共用修复配额）
_FABRICATION_REPAIR_HINT = (
    "上一轮收尾声称已「{claim}」，但本回合没有对应工具的成功执行记录。"
    "请只陈述工具结果已证实的内容：如需发起确认卡或创建任务，先调用相应工具，"
    "不要声称未实际执行的平台操作。"
)

_PLAN_SYSTEM = (
    "你是评测平台对话引擎的规划器。只输出一个 JSON 对象，不要输出任何其他文字。\n"
    '格式：{"intent":"一句话意图","skill_id":null或技能ID,"slots":{"steps":'
    '["第1步",...3到7步],其他槽位},"tools_needed":["只读短工具名"],'
    '"delivery":"chat","budget":{"model_calls":12,"tool_turns":8},'
    '"allows_replan":false,"notes":"不超过40字说明",'
    '"protocol":"plan","version":"plan.v1"}\n'
    "要求：步骤必须 3–7 步；tools_needed 只列短工具；探索任务 delivery=chat。\n"
    "intent 是执行环境的路由依据，必须从以下语义词中明确表述（不要用抽象概括，"
    "不要自造新词）：排查/诊断/定位/分析（排查类）；数据集/整理/清单（数据类）；"
    "运行脚本/执行命令/跑脚本/运行代码（脚本执行类）。涉及脚本执行时 intent 必须"
    "显式包含上述执行类语义词，否则执行器无法获得对应能力。"
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

# F0/P1：原生工具装配轮的执行指令（V0.2 D1 双通道裁剪）——工具 schema 正文
# 不再注入 system（定义经协议 tools 下发），保留 react.v1 格式说明作为回退
# 提示，并附 L1 纪律精简段（禁编造/密钥保护，语义同源 system.py L1，长度
# 受控为执行轮精简版）。回退到文本协议时恢复 _REACT_SYSTEM_TEMPLATE 全量。
_REACT_NATIVE_SYSTEM = (
    "你是评测平台对话引擎的执行器。本轮携带平台原生工具定义（tools 参数），"
    "优先使用原生工具调用完成目标动作：\n"
    "- 需要工具时发起原生工具调用；只能用下发的工具，不得编造工具名或伪造参数；\n"
    "- 工具结果会以工具消息回填；未收到工具结果前不得声称操作已成功；\n"
    "- 不得在输出中暴露 API Key、Cookie、密码、Token 或任何密钥类信息。\n"
    "若本轮没有收到工具定义或原生工具不可用，则按文本协议输出一个 JSON 对象"
    "（字段：thought 为不超过 30 字的摘要；tool 为工具名或 null；arguments 为"
    "对象；done 为布尔；protocol 恒为 react；version 恒为 react.v1；"
    "done=true 时在 JSON 之后另起一行输出给用户的最终答复正文）。\n"
    "规则：已经重复读取过同一文件/检索过同一内容时，直接结束，不要重复调用。\n"
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
    tools: tuple[Mapping[str, object], ...] = (),
) -> tuple[ModelRequest, dict]:
    """按会话协议档组装 ModelRequest（api_key 即时注入，不入 State）。

    F0/P1：``tools`` 由调用节点按装配许可传入（仅 orchestrator 执行轮装配，
    见 _REACT_NATIVE_SYSTEM；plan/reflect 不装配）。默认空元组 = 与现状一致，
    适配器不写请求体 ``"tools"`` 键。
    """
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
    request = ModelRequest(  # type: ignore[arg-type]
        config=model_config, messages=tuple(messages), system=system, tools=tools
    )
    return request, configurable


def _merge_usage(
    base: Mapping[str, object] | None, usage: Mapping[str, object] | None
) -> dict[str, int]:
    """回合累计模型 token usage（F0/P1 审计；计数键相加，非计数键忽略）。

    agent 图内每次模型调用（plan/orchestrator/reflect L3）都把响应 usage 并入，
    最终随收尾 assistant_message 的 turn_stats 落库（对齐 chat 路径 routing.py
    的 usage 口径，R3-M1 计量修复）。仅含计数，无正文，可安全入检查点。
    """
    merged: dict[str, int] = {}
    for source in (base, usage):
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                merged[key] = int(merged.get(key, 0)) + int(value)
    return merged


def _observation_lines(state: GraphState) -> list[str]:
    """取最近若干条 Observation 文本（注入模型输入；Observation 只作模型输入）。

    F0/P2：原生轮的占位观察（toolnode 以占位文本落 observations，正文只进
    NativeToolResultStore）**跳过文本注入**——该轮正文已随 role=tool 回填，
    占位重复注入只会制造噪音；占位观察仍留 state 供 H4 失败阶梯与 OR-4 守卫。
    """
    observations = list(state.get("observations") or [])
    lines: list[str] = []
    for observation in observations[-_MAX_INJECTED_OBSERVATIONS:]:
        if not isinstance(observation, Mapping):
            continue
        text = str(observation.get("text") or "")
        if _NATIVE_OBSERVATION_PLACEHOLDER in text:
            continue
        tool = str(observation.get("tool") or "")
        if len(text) > _MAX_OBSERVATION_CHARS:
            text = text[:_MAX_OBSERVATION_CHARS] + "…"
        ok = "成功" if observation.get("ok") else "失败"
        lines.append(f"[工具 {tool} 执行{ok}]\n{text}")
    return lines


def _clip_backfill_text(content: str) -> str:
    """回填正文二次裁剪（store 600K → 模型输入上限，带截断标注）。"""
    if len(content) <= _MAX_BACKFILL_CHARS:
        return content
    return content[:_MAX_BACKFILL_CHARS] + _BACKFILL_TRUNCATE_NOTICE.format(
        limit=_MAX_BACKFILL_CHARS
    )


def _build_native_backfill(
    native_round: Mapping[str, object],
    native_tool_results: object | None,
    thread_id: str,
) -> list[Mapping[str, object]]:
    """合成上一原生轮的回填消息对（内部规范，适配层转换协议形态）。

    形态 = ``assistant(tool_calls…)`` 紧跟 ``role=tool`` 正文对（anthropic 的
    tool_result 须紧邻对应 tool_use；本函数保证次序与完整性）。正文从
    NativeToolResultStore 取（含失败/拒绝路径的正文与 repair 提示——R3-M5），
    缺失时以显式降级文案替代（不伪造正文，R1-M5）。单条二次裁剪防上下文
    溢出（R1-M4）。
    """
    assistant = native_round.get("assistant")
    if not isinstance(assistant, Mapping):
        return []
    calls = assistant.get("tool_calls")
    if not isinstance(calls, list | tuple) or not calls:
        return []
    backfill: list[Mapping[str, object]] = [dict(assistant)]
    get = getattr(native_tool_results, "get", None)
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        call_id = str(call.get("call_id") or "").strip()
        name = str(call.get("name") or "")
        content: str = ""
        if get is not None and call_id:
            stored = get(thread_id, call_id) if thread_id else None
            content = str(stored or "") if isinstance(stored, str) else ""
        if not content.strip():
            content = _NATIVE_BACKFILL_MISSING_TEXT
        backfill.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": _clip_backfill_text(content),
            }
        )
    return backfill


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
    """收尾事件对：``assistant_message`` + ``response.completed``（后者必须最后一条）。

    F0/P1：assistant_message 携带 turn_stats.usage（回合累计模型 token 用量，
    与 chat 路径 routing.py 同构，R3-M1 成本审计）；用量为空时省略该键。
    """
    payload: dict[str, object] = {"text": text, "role": "assistant", "latency_ms": 0}
    usage = _merge_usage(state.get("turn_usage"), None)
    if usage:
        payload["turn_stats"] = {"usage": usage}
    return [
        make_event("assistant_message", payload),
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
