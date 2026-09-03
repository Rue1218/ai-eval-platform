"""混合引擎 H2：Workflow DAG 八节点（engine=workflow 的确定性执行链）。

节点顺序（唯一、硬编码、无跳步/回溯/合并，开发计划 V1.3 H2）：

    W0 select_skill → W1 prepare_slots → W2 load_skill → W3 validate_gates
        → W4 build_task_spec → W5 await_confirm → W6 enqueue → W7 summarize

约束（与开发计划 H2 验收一致）：
- 节点只返回纯数据；DB 与 WebSocket 资源经 ``RunnableConfig.configurable``
  注入（``db_factory`` / ``session_id`` / ``user_id`` / ``workflow_confirm``），
  不入 GraphState（M3-D2 先例）；
- 节点失败只能就地收尾（error 事件 + ``workflow_failed``），不能改写下一跳
  或形成重试回环；条件边见 ``graph.py``；
- ``confirm_id`` 与 ``clarify_id`` 互斥；``engine=workflow`` 时 ``replan_count``
  恒为 0（W0–W7 无重规划）；
- W0 二段路由：业务歧义（零命中 / 并列）**禁止猜测**，错误消息就地收尾；
  非法 / 已禁用 ``skill_id``（skill-rag）→ VALIDATION fail-closed；
- W6 是唯一入队出口（``enqueue_long_task``）；确认动作的行锁事务（
  ``pending_confirm`` 清卡）由 ws 直连层承担（H2 批次 2，图内不 interrupt）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from langgraph.config import RunnableConfig, get_config

from app.errors import AppError
from app.harness.contracts import make_event
from app.harness.feedback.rules import CONFIRM_KINDS
from app.harness.memory import GraphState, SerializableRequest
from app.harness.orchestration.router import has_workflow_execution_intent
from app.harness.skills import SKILL_CATALOG, load_skill_workflow, skill_to_kind

# ── 技能候选关键词（目录单一事实源 + 别名；命中即技能意图候选）──
_SKILL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("skill-benchmark", ("基准评测", "评测", "benchmark", "跑分")),
    ("skill-testcase", ("用例生成", "测试用例", "用例", "testcase")),
    ("skill-stress", ("压测", "stress", "压测任务")),
    ("skill-rag", ("知识库评测", "知识库", "rag")),
)

# 「rag/知识库评测」复合词：折叠为单一技能意图，避免「跑 rag 评测」被
# 「评测」命中 benchmark 造成并列歧义（对齐 router_node 的折叠语义）。
_RAG_EVAL_COMPOUND = re.compile(
    r"(?:rag|知识库)\s*(?:质量)?\s*评测|评测\s*(?:质量)?\s*(?:rag|知识库)"
)

# 技能 → 必填资产槽（确认卡兜底；profile 三技能都要）
_REQUIRED_ASSETS: dict[str, tuple[str, ...]] = {
    "benchmark": ("profile_ids",),
    "testcase": ("profile_ids",),
    "stress": ("profile_ids",),
    "rag": ("kb_id", "gold_qa_id"),
}

# 入队成功后的平台收尾文案模板（确定性、无模型调用）
_ENQUEUE_SUMMARY = {
    "benchmark": "基准评测任务已入队，进度与报告将在对话中实时更新。",
    "testcase": "用例生成任务已入队，进度与报告将在对话中实时更新。",
    "stress": "压测任务已入队，进度与报告将在对话中实时更新。",
}


def _latest_user_text(serializable: SerializableRequest) -> str:
    """提取本轮最后一条用户消息文本（与 router 节点同口径）。"""
    for message in reversed(list(serializable.get("messages") or ())):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _configurable() -> dict:
    """读取当前 RunnableConfig.configurable（缺省为空映射）。

    节点必然在图内执行（有 run 上下文）；图外直接调用（单测）时容错返回空
    映射，保证节点函数可独立断言（依赖缺失按各自语义失败）。
    """
    try:
        run_config = get_config()
    except RuntimeError:
        return {}
    return dict((run_config or {}).get("configurable") or {})


def _skill_candidates(text: str) -> tuple[str, ...]:
    """文本中的技能候选（目录序去重）；rag 复合词先折叠。"""
    if _RAG_EVAL_COMPOUND.search(text):
        return ("skill-rag",)
    hits: list[str] = []
    for skill_id, keywords in _SKILL_KEYWORDS:
        if skill_id == "skill-rag":
            continue  # 复合词已单独处理；裸「知识库/rag」词不作为基准评测并列源
        if any(keyword in text for keyword in keywords) and skill_id not in hits:
            hits.append(skill_id)
    return tuple(hits)


def _error_events(code: str, message: str) -> list[dict]:
    """就地收尾 error 事件（只透错误码与消息，不含内部细节）。"""
    return [make_event("error", {"code": code, "message": message})]


def _step(name: str) -> dict:
    """节点推进标记（可观测：workflow_step 记录当前节点）。"""
    return {"workflow_step": name}


def _completed_payload(state: GraphState, finish_reason: str) -> dict[str, object]:
    """回合收尾 completed payload；engine 已写入时携带 Router 审计三元组。"""
    payload: dict[str, object] = {"finish_reason": finish_reason, "role": "assistant"}
    engine = state.get("engine")
    if engine is not None:
        payload.update(
            engine=engine,
            router_confidence=state.get("router_confidence"),
            router_reason=state.get("router_reason"),
        )
    return payload


def _narrate(text: str) -> dict:
    """阶段叙述事件意图（assistant_message；单回合多条，API.md V1.67）。"""
    return make_event("assistant_message", {"text": text, "role": "assistant", "latency_ms": 0})


# ── W0 select_skill：二段路由（确定性；业务歧义就地收尾，禁止猜测）──


def select_skill_node(state: GraphState) -> dict:
    """W0：从用户文本二段路由选定技能。

    单候选 → 选定；rag（已禁用）→ VALIDATION fail-closed；并列 / 零命中 →
    就地收尾（歧义提示，不猜测技能、不产生任务）。
    """
    text = _latest_user_text(state["request"])
    # H1 的 L1 仅是建议性分类；即使上游误把概念问答投到 workflow，
    # W0 也必须再次确认用户确有执行意图，避免错误地发出确认卡。
    if not has_workflow_execution_intent(text):
        return {
            **_step("W0_select_skill"),
            "workflow_failed": True,
            "pending_events": _error_events(
                "VALIDATION", "请明确说明要执行的评测任务；概念问答可直接提问"
            ),
        }
    candidates = _skill_candidates(text)
    if len(candidates) == 1:
        skill_id = candidates[0]
        if skill_id in SKILL_CATALOG and skill_id == "skill-rag":
            return {
                **_step("W0_select_skill"),
                "workflow_failed": True,
                "pending_events": _error_events(
                    "VALIDATION", "知识库评测（RAG）未接入，暂无法执行"
                ),
            }
        return {
            **_step("W0_select_skill"),
            "skill_id": skill_id,
            "skill_candidates": candidates,
        }
    if len(candidates) > 1:
        names = "、".join(SKILL_CATALOG[skill_id][0] for skill_id in candidates)
        return {
            **_step("W0_select_skill"),
            "workflow_failed": True,
            "pending_events": _error_events(
                "VALIDATION", f"检测到多个评测意图（{names}），请明确要执行哪一项"
            ),
        }
    return {
        **_step("W0_select_skill"),
        "workflow_failed": True,
        "pending_events": _error_events(
            "VALIDATION", "无法识别评测类型（当前支持：基准评测 / 用例生成 / 压测）"
        ),
    }


# ── W1 prepare_slots：确定性槽位与缺失清单（LLM 抽取随 H3 工具批）──


def prepare_slots_node(state: GraphState) -> dict:
    """W1：初始化槽位并按技能列出缺失必填资产。

    H2 版本为确定性映射（无 LLM）：默认值已在 W4 经 ``default_task_spec``
    预填，本节点只登记缺失的资产槽供确认卡展示；槽位抽取的 LLM 增强
    与只读工具视野随 H3 一并落地。
    """
    skill_id = state.get("skill_id")
    if not skill_id or state.get("workflow_failed"):
        return _step("W1_prepare_slots")
    kind = skill_to_kind(skill_id)
    missing = list(_REQUIRED_ASSETS.get(kind, ()))
    return {
        **_step("W1_prepare_slots"),
        "slots": {},
        "slots_missing": tuple(missing),
    }


# ── W2 load_skill：技能正文加载校验（fail-closed 双保险）──


def load_skill_node(state: GraphState) -> dict:
    """W2：按需加载技能工作流（校验启用；正文不写 State，SK-1）。"""
    skill_id = state.get("skill_id")
    if not skill_id or state.get("workflow_failed"):
        return _step("W2_load_skill")
    try:
        load_skill_workflow(skill_id)  # assert_skill_enabled 内含 rag fail-closed
    except AppError as exc:
        return {
            **_step("W2_load_skill"),
            "workflow_failed": True,
            "pending_events": _error_events(exc.code.value, str(exc)),
        }
    return _step("W2_load_skill")


# ── W3 validate_gates：确定性门禁（kind / 先评后压 / 会话占槽）──


def validate_gates_node(state: GraphState, *, config: RunnableConfig | None = None) -> dict:
    """W3：门禁先行（规则与 feedback.rules 同源语义）。

    - kind 白名单：非四类评测 kind 拒绝（防御）；
    - 先评后压：直接请求 stress（无 parent 派生链）拒绝；
    - 会话占槽：``configurable["session_probe"]``（ws 注入可调用返回
      ``has_active_task``）存在且为 True 时拒绝；未注入跳过并注记。
    """
    skill_id = state.get("skill_id")
    if not skill_id or state.get("workflow_failed"):
        return _step("W3_validate_gates")
    kind = skill_to_kind(skill_id)
    failed_code: str | None = None
    message: str | None = None
    if kind not in CONFIRM_KINDS:
        failed_code, message = "VALIDATION", f"未知任务类型：{kind}"
    elif kind == "stress":
        failed_code, message = "VALIDATION", "压测任务须由质量评测成功派生（先评后压）"
    elif kind == "rag":
        failed_code, message = "VALIDATION", "知识库评测（RAG）未接入，暂无法执行"
    else:
        probe = (config if config is not None else _configurable()).get("session_probe")
        has_active = False
        if callable(probe):
            try:
                has_active = bool(probe())
            except Exception:
                has_active = False
        if has_active:
            failed_code, message = "CONCURRENCY", "会话存在活动任务，请先完成或取消后再发起"
    report: dict[str, Any] = {
        "passed": failed_code is None,
        "workflow_step": "W3_validate_gates",
    }
    if failed_code:
        report["failed_code"] = failed_code
        report["message"] = message
        return {
            **_step("W3_validate_gates"),
            "workflow_failed": True,
            "gate_report": report,
            "pending_events": _error_events(failed_code, message or "门禁未通过"),
        }
    return {**_step("W3_validate_gates"), "gate_report": report}


# ── W4 build_task_spec：TaskSpec 装配（defaults.py 单一事实源）──


def build_task_spec_node(state: GraphState) -> dict:
    """W4：按 kind 产出确认卡 TaskSpec 预填骨架（``default_task_spec``）。"""
    skill_id = state.get("skill_id")
    if not skill_id or state.get("workflow_failed"):
        return _step("W4_build_task_spec")
    from app.agent.defaults import default_task_spec

    kind = skill_to_kind(skill_id)
    return {**_step("W4_build_task_spec"), "task_spec": default_task_spec(kind)}


# ── W5 await_confirm：必填资产确认（图内不 interrupt，直连由 ws 层承担）──


def await_confirm_node(state: GraphState, *, config: RunnableConfig | None = None) -> dict:
    """W5：确认门槛（H2 批次 2：无确认上下文时发卡收尾，有则合并放行 W6）。 (feat(agent): H2 批次 2 确认卡链路——W5 发卡与 ack 重放经 W6 唯一入队)

    - ``configurable["workflow_confirm"]``（ws 直连层确认回执注入的载荷）存在时：
      合并槽位并校验必填资产 → 通过放行 W6，缺失就地收尾（error + 收尾 completed）；
    - 不存在时：**发出确认卡**（``confirm`` 事件携带 W4 的 TaskSpec）并收尾本轮
      （``workflow_failed`` 表示本轮链未走完，等待回执重放；H5 前图内不 interrupt）。
    """
    skill_id = state.get("skill_id")
    if not skill_id or state.get("workflow_failed"):
        return _step("W5_await_confirm")
    confirm = (config if config is not None else _configurable()).get("workflow_confirm")
    if not isinstance(confirm, Mapping) or not confirm:
        # 首次到达 W5：发卡收尾（卡即补槽 UI），不推进 W6
        spec = dict(state.get("task_spec") or {})
        missing = state.get("slots_missing") or ()
        hint = "（卡上已按平台默认值预填，请补齐必填项后确认）" if missing else "（请核对后确认）"
        message = f"任务单已生成{hint}。"
        return {
            **_step("W5_await_confirm"),
            "workflow_failed": True,  # 本轮链到此收尾，等 ws 层回执重放
            "confirm_id": uuid4().hex,
            "pending_events": [
                _narrate(message),
                make_event("confirm", spec),
                make_event("response.completed", _completed_payload(state, "stop")),
            ],
            "response": {"text": message, "usage": {}, "latency_ms": 0},
        }
    kind = skill_to_kind(skill_id)
    spec = dict(state.get("task_spec") or {})
    patch = dict(confirm.get("task_spec") or {}) if isinstance(confirm, Mapping) else {}
    for key, value in patch.items():
        if value is not None:
            spec[key] = value
    missing = [
        slot
        for slot in _REQUIRED_ASSETS.get(kind, ())
        if not spec.get(slot)
    ]
    if missing:
        return {
            **_step("W5_await_confirm"),
            "workflow_failed": True,
            "slots_missing": tuple(missing),
            "pending_events": [
                *_error_events(
                    "VALIDATION",
                    f"确认卡缺少必填项：{', '.join(missing)}（请补齐后重试）",
                ),
                make_event("response.completed", _completed_payload(state, "error")),
            ],
        }
    return {**_step("W5_await_confirm"), "task_spec": spec}


# ── W6 enqueue：唯一入队出口（内部 MCP 长任务桥）──


def enqueue_node(state: GraphState, *, config: RunnableConfig | None = None) -> dict:
    """W6：经 ``enqueue_long_task`` 原子入队（唯一 W6 出口）。

    ``configurable`` 注入 ``db_factory`` / ``session_id`` / ``user_id``；
    缺失上下文 → INTERNAL 就地收尾（图内不猜测）。
    """
    skill_id = state.get("skill_id")
    if not skill_id or state.get("workflow_failed"):
        return _step("W6_enqueue")
    from app.harness.execution.worker_bridge import enqueue_long_task

    configurable = config if config is not None else _configurable()
    db_factory = configurable.get("db_factory")
    session_id = str(configurable.get("session_id") or "")
    user_id = str(configurable.get("user_id") or "")
    if not callable(db_factory):
        return {
            **_step("W6_enqueue"),
            "workflow_failed": True,
            "pending_events": _error_events("INTERNAL", "任务执行器上下文缺失"),
        }
    kind = skill_to_kind(skill_id)
    spec = dict(state.get("task_spec") or {})
    try:
        db = db_factory()
        try:
            task_id = enqueue_long_task(db, session_id, user_id, kind, spec)
        finally:
            db.close()
    except AppError as exc:
        return {
            **_step("W6_enqueue"),
            "workflow_failed": True,
            "pending_events": _error_events(exc.code.value, str(exc)),
        }
    return {**_step("W6_enqueue"), "enqueued_task_id": task_id}


# ── W7 summarize：平台模板收尾（零模型调用，携带 engine 审计）──


def summarize_node(state: GraphState) -> dict:
    """W7：入队成功的平台收尾（assistant_message + completed 审计）。"""
    skill_id = state.get("skill_id")
    if state.get("workflow_failed") or not skill_id:
        return _step("W7_summarize")
    kind = skill_to_kind(skill_id)
    task_id = str(state.get("enqueued_task_id") or "")
    text = _ENQUEUE_SUMMARY.get(kind, "任务已入队，进度与报告将在对话中实时更新。")
    if task_id:
        text = f"{text}（任务 ID：{task_id}）"
    # 收尾 completed 与 W5 发卡收尾共用同一构造（engine 审计三元组）
    completed_payload = _completed_payload(state, "stop")
    return {
        **_step("W7_summarize"),
        "pending_events": [
            make_event(
                "assistant_message",
                {"text": text, "role": "assistant", "latency_ms": 0},
            ),
            make_event("response.completed", completed_payload),
        ],
        "response": {"text": text, "usage": {}, "latency_ms": 0},
        "confirm_id": None,  # 引擎 workflow 完成时确认卡已消费（与 clarify 互斥）
    }


def workflow_failure_node(state: GraphState) -> dict:
    """统一收尾未自行结束的 Workflow 失败路径。

    W0、W2、W3、W6 会先产出 ``error`` 供前端展示，却不能各自遗漏
    ``response.completed``。W5 的确认卡/缺槽路径已自行收尾，图条件边会避开
    本节点，从而保证一个回合恰好一个 completed 事件。
    """
    return {
        **_step("workflow_failure"),
        "pending_events": [
            make_event("response.completed", _completed_payload(state, "error"))
        ],
        "response": {"text": "", "usage": {}, "latency_ms": 0},
    }
