"""规划阶段：PlanArtifact 解析、斜杠模板、LLM 调用与 L0 降级（HAR-PLAN）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from .defaults import (
    CONFIRM_SLOT_KEYS,
    DEFAULT_TOOL_ROUNDS,
    DEFAULT_TOOLS_BY_INTENT,
    DELIVERY_ENUM,
    HARD_MAX_TOOL_ROUNDS,
    INTENT_ENUM,
    REQUIRED_SLOTS,
    SHORT_TOOLS,
    SKILL_ID_ENUM,
    WRITE_TOOLS,
    is_long_tool,
)
from .imagegen import inject_imagegen_plan, looks_like_image_generation
from .log import agent_trace
from .persona import PLAN_RETRY_SUFFIX, REPLAN_JSON_SUFFIX, plan_system, turn_system
from .slash import SlashParse
from .voiceclone import inject_voiceclone_plan


@dataclass
class PlanArtifact:
    """规划产物。字段名冻结，不可增删改名。"""

    intent: str
    skill_id: str | None
    slots: dict[str, Any]
    tools_needed: list[str]
    delivery: str
    budget: dict[str, int]
    notes: str
    used_model: bool = False
    latency_ms: int = 0
    source: str = "llm"  # llm | slash | l0 | retry | replan
    # 规划阶段沿用偏好时要发的思考卡（不写入 PlanArtifact JSON）
    pref_thoughts: list[str] = field(default_factory=list)
    # 模型判定的范式与复杂度；不进 as_dict（确认卡字段冻结）
    loop: str = ""
    complexity: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "skill_id": self.skill_id,
            "slots": self.slots,
            "tools_needed": list(self.tools_needed),
            "delivery": self.delivery,
            "budget": dict(self.budget),
            "notes": self.notes,
        }


@dataclass
class TurnBudget:
    """单回合模型调用计数（不含 /compact）。"""

    used: int = 0
    cap: int = 4

    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    def consume(self) -> bool:
        """尝试占用一次模型调用；达顶返回 False。"""
        if self.used >= self.cap:
            return False
        self.used += 1
        return True


def parse_json_object(text: str) -> dict:
    """从模型输出中容错提取 JSON 对象（允许围栏与首尾文字）。"""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回可解析的 JSON 对象")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


# 兼容 ws 单测旧名
parse_llm_json = parse_json_object


def _clip_slots(raw: Any) -> dict[str, Any]:
    """只保留确认卡字段；未知键丢弃并记录。"""
    filled_in = raw.get("filled") if isinstance(raw, dict) else {}
    missing_in = raw.get("missing") if isinstance(raw, dict) else []
    filled: dict[str, Any] = {}
    if isinstance(filled_in, dict):
        for key, value in filled_in.items():
            if key in CONFIRM_SLOT_KEYS:
                filled[key] = value
            else:
                agent_trace(f"规划丢弃未知槽位键 key={key}")
    missing: list[str] = []
    if isinstance(missing_in, list):
        for key in missing_in:
            if isinstance(key, str) and key in CONFIRM_SLOT_KEYS:
                missing.append(key)
            elif key:
                agent_trace(f"规划丢弃未知 missing 键 key={key}")
    return {"filled": filled, "missing": missing}


def sanitize_plan(raw: dict, *, source: str = "llm") -> PlanArtifact:
    """把任意 dict 收成合法 PlanArtifact（HAR-PLAN-02）。"""
    intent = str(raw.get("intent") or "").strip().lower()
    if intent not in INTENT_ENUM:
        raise ValueError(f"非法 intent={intent}")
    skill_raw = raw.get("skill_id")
    skill_id: str | None
    if skill_raw in (None, "", "null"):
        skill_id = None
    else:
        skill_id = str(skill_raw).strip()
        if skill_id not in SKILL_ID_ENUM:
            agent_trace(f"非法 skill_id 置 null value={skill_id}")
            skill_id = None

    tools: list[str] = []
    for name in raw.get("tools_needed") or []:
        if not isinstance(name, str):
            continue
        tool = name.strip()
        if tool:
            tools.append(tool)

    delivery = str(raw.get("delivery") or "clarify").strip().lower()
    if delivery not in DELIVERY_ENUM:
        delivery = "clarify"

    budget_in = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}
    try:
        rounds = int(budget_in.get("max_tool_rounds", DEFAULT_TOOL_ROUNDS))
    except (TypeError, ValueError):
        rounds = DEFAULT_TOOL_ROUNDS
    rounds = max(0, min(rounds, HARD_MAX_TOOL_ROUNDS))

    notes = str(raw.get("notes") or "").strip()
    slots = _clip_slots(raw.get("slots") if isinstance(raw.get("slots"), dict) else {})
    if "kind" not in slots["filled"] and intent in {"benchmark", "rag", "testcase"}:
        slots["filled"]["kind"] = intent

    loop = _clip_loop(raw.get("loop"), intent=intent, tools=tools)
    complexity = str(raw.get("complexity") or "").strip().lower()
    if complexity not in {"low", "medium", "high"}:
        complexity = _default_complexity(loop)

    return PlanArtifact(
        intent=intent,
        skill_id=skill_id,
        slots=slots,
        tools_needed=tools,
        delivery=delivery,
        budget={"max_tool_rounds": rounds},
        notes=notes,
        source=source,
        loop=loop,
        complexity=complexity,
    )


LOOP_ENUM = frozenset({"chat", "react", "plan_solve"})


def _clip_loop(raw_loop: Any, *, intent: str, tools: list[str]) -> str:
    """模型给出的 loop 优先；缺省时按 intent/工具推断。"""
    loop = str(raw_loop or "").strip().lower()
    if loop in LOOP_ENUM:
        return loop
    if intent in {"benchmark", "rag", "testcase", "rerun"}:
        return "plan_solve"
    if tools:
        return "react"
    if intent == "inspect":
        return "react"
    return "chat"


def _default_complexity(loop: str) -> str:
    if loop == "plan_solve":
        return "high"
    if loop == "react":
        return "medium"
    return "low"


def _stamp_loop(plan: PlanArtifact) -> PlanArtifact:
    """补全 runtime 的 loop/complexity，不写入确认卡 JSON。"""
    tools = list(plan.tools_needed or [])
    if "image.generate" in tools or "audio.voiceclone" in tools:
        plan.loop = "react"
    elif plan.loop not in LOOP_ENUM:
        plan.loop = _clip_loop(plan.loop, intent=plan.intent, tools=tools)
    if plan.complexity not in {"low", "medium", "high"}:
        plan.complexity = _default_complexity(plan.loop)
    return plan


# 高置信闲聊提示（不含「其它 → chat」兜底）。仅 L0 分类与关键词回退使用；自然语言规划不再短路。
CHAT_HINTS = ("你好", "您好", "介绍", "你是谁", "天气", "谢谢", "闲聊", "随便聊聊", "hello", "hi ")
# 评测口令。禁止用光杆「对比」：摄影提示词里的明暗对比/冷暖对比会误判成 benchmark。
EVAL_INTENT_HINTS = (
    "benchmark",
    "评测",
    "评估",
    "跑分",
    "打分",
    "测试模型",
    "模型质量",
    "评一下",
    "帮我评",
    "基准对比",
    "模型对比",
    "对比评测",
    "对比两个",
    "对比几个",
    "对比一下模型",
)
# 与评测关键词重叠时不得当闲聊，避免「你好，帮我评一下」跳过规划
EVAL_BLOCK_HINTS = EVAL_INTENT_HINTS


def is_smalltalk(text: str) -> bool:
    """问候/闲聊关键词且无评测关键词。不含含糊句的 chat 兜底。"""
    raw = text or ""
    lowered = raw.lower()
    if any(k in raw for k in EVAL_BLOCK_HINTS):
        return False
    return any(k.lower() in lowered for k in CHAT_HINTS)


# 只读查询：一两步 list/get，走 ReAct，不套评测技能
INSPECT_QUERY_RE = re.compile(
    r"(列出(协议档|数据集|知识库|任务)|有哪些(协议档|数据集|模型)|调度概览)"
)


def looks_like_inspect_query(text: str) -> bool:
    """用户只要清单/概览，不是下单评测。"""
    raw = text or ""
    if any(k in raw for k in ("评测", "评估", "帮我评", "评一下", "benchmark", "跑分", "打分", "测试模型")):
        return False
    return bool(INSPECT_QUERY_RE.search(raw))


def inspect_tools_needed(text: str) -> list[str]:
    """按查询对象选一个短工具。"""
    raw = text or ""
    if "数据集" in raw:
        return ["dataset.list"]
    if "知识库" in raw:
        return ["kb.list"]
    if "调度" in raw:
        return ["dispatch.overview"]
    if "任务" in raw:
        return ["task.get"]
    return ["model.list"]


def classify_intent_l0(text: str) -> tuple[str, bool]:
    """L0 规则意图（不区分大小写、命中先到先得）。

    返回 (intent, with_stress)。闲聊关键词在「其它 → benchmark」之前，
    以满足 TC-15；评测关键词仍按 HAR-PLAN-05 表。
    """
    raw = text or ""
    lowered = raw.lower()
    if any(k.lower() in lowered for k in ("PRD", "用例", "测试用例", "生成用例")):
        return "testcase", False
    if any(k in raw for k in ("RAG", "知识库", "检索", "召回", "LightRAG", "黄金")) or "lightrag" in lowered:
        stress = any(k in raw for k in ("压测", "加压", "先评后压", "QPS", "qps"))
        return "rag", stress
    if "解读" in raw and "报告" in raw:
        return "report", False
    if any(k in raw for k in ("压测", "加压", "先评后压", "QPS", "qps")):
        return "benchmark", True
    if "/compact" in lowered:
        return "compact", False
    if is_smalltalk(text):
        # HAR-PLAN-05 表「其它 → benchmark」与 TC-15 闲聊验收冲突时，按 TC-15 走 chat。
        return "chat", False
    if any(k in lowered for k in EVAL_INTENT_HINTS):
        return "benchmark", False
    # HAR-PLAN-05：其它 → benchmark（缺槽走 clarify，不出假卡）
    if raw.startswith("/"):
        return "benchmark", False
    return "chat", False


def l0_plan(text: str, *, prefs: dict | None = None) -> PlanArtifact:
    """L0 降级产物形状（评审默认方案 D1）。仍必须进入复核。"""
    if looks_like_image_generation(text):
        return _stamp_loop(
            PlanArtifact(
            intent="chat",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=["image.generate"],
            delivery="text",
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes="规划：使用 Qwen Image 生成图片",
            source="l0",
            )
        )
    if looks_like_inspect_query(text):
        tools = inspect_tools_needed(text)
        return _stamp_loop(
            PlanArtifact(
            intent="inspect",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=tools,
            delivery="text",
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes=f"规划：查询 {tools[0]}。",
            source="l0",
            )
        )
    intent, with_stress = classify_intent_l0(text)
    filled: dict[str, Any] = {}
    if intent in {"benchmark", "rag", "testcase"}:
        filled["kind"] = intent
    if with_stress:
        filled["with_stress"] = True
        if prefs and prefs.get("last_kind") == "rag" and intent == "benchmark":
            filled["kind"] = "rag"
            intent = "rag"
    missing: list[str] = list(REQUIRED_SLOTS.get(filled.get("kind", intent), ()))
    if with_stress and "stress" not in missing:
        missing.append("stress")
    tools = list(DEFAULT_TOOLS_BY_INTENT.get(intent, []))
    if intent == "inspect":
        tools = []
    delivery = "confirm" if not missing and intent in {"benchmark", "rag", "testcase"} else "clarify"
    if intent in {"chat", "compact", "cancel"}:
        delivery = "text" if intent == "chat" else "action"
        missing = []
        tools = [] if intent != "cancel" else ["task.get"]
    if intent == "report":
        delivery = "text"
    notes = f"规划：已按规则识别为 {intent}。"
    skill_id = {
        "benchmark": "skill-benchmark",
        "rag": "skill-rag",
        "testcase": "skill-testcase",
    }.get(intent)
    if with_stress:
        skill_id = "skill-stress"
    return _stamp_loop(
        PlanArtifact(
        intent=intent,
        skill_id=skill_id,
        slots={"filled": filled, "missing": missing},
        tools_needed=tools,
        delivery=delivery,
        budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
        notes=notes,
        source="l0",
        )
    )


def plan_from_slash(parsed: SlashParse, *, prefs: dict | None, attachments: list[str]) -> PlanArtifact:
    """仅处理不注入业务工具的会话控制斜杠。"""
    command = parsed.command or ""
    if command == "compact":
        return PlanArtifact(
            intent="compact",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=[],
            delivery="action",
            budget={"max_tool_rounds": 0},
            notes="规划：压缩本会话模型窗口。",
            source="slash",
        )
    # 未知命令不会走到这里；保留安全回退，禁止将其解释为业务意图。
    return PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=[],
        delivery="text",
        budget={"max_tool_rounds": 0},
        notes="规划：未知命令。",
        source="slash",
    )


def apply_prefs_suggestions(plan: PlanArtifact, prefs: dict) -> list[str]:
    """缺槽且用户没点名资产时，把上次值当作建议填入 filled（仍须工具校验）。

    返回需要发的思考卡说明。
    """
    thoughts: list[str] = []
    filled = plan.slots.setdefault("filled", {})
    missing = list(plan.slots.get("missing") or [])
    if plan.intent not in {"benchmark", "rag", "testcase"}:
        return thoughts
    if "profile_ids" in missing and not filled.get("profile_ids") and prefs.get("last_profile_ids"):
        filled["profile_ids"] = list(prefs["last_profile_ids"])
        thoughts.append("沿用你上次的协议档，可在卡上改")
    if "dataset_id" in missing and not filled.get("dataset_id") and prefs.get("last_dataset_id"):
        filled["dataset_id"] = prefs["last_dataset_id"]
        thoughts.append("沿用你上次的数据集，可在卡上改")
    if plan.intent == "rag":
        if "kb_id" in missing and prefs.get("last_kb_id"):
            filled["kb_id"] = prefs["last_kb_id"]
        if "gold_qa_id" in missing and prefs.get("last_gold_qa_id"):
            filled["gold_qa_id"] = prefs["last_gold_qa_id"]
    # with_stress 仅 benchmark/rag 合法；testcase 沿用会让确认卡 ack 被 TaskCreate 拒绝
    if (
        plan.intent in {"benchmark", "rag"}
        and prefs.get("last_with_stress")
        and "with_stress" not in filled
    ):
        filled["with_stress"] = True
    return thoughts


def _attach_prefs(plan: PlanArtifact, prefs: dict) -> PlanArtifact:
    """把偏好建议写入 filled，并把思考卡文案挂到 plan.pref_thoughts（HAR-PLAN-06）。"""
    extra = apply_prefs_suggestions(plan, prefs)
    if extra:
        plan.pref_thoughts.extend(extra)
    return plan


def _call_plan_model(
    db: Session,
    user_payload: dict,
    *,
    extra_system: str,
    budget: TurnBudget,
    compact_summary: str | None = None,
) -> tuple[dict, int]:
    if not budget.consume():
        raise AppError(ErrorCode.VALIDATION, "本轮模型调用已达上限")
    from ..llm import call_agent_model_detailed

    result = call_agent_model_detailed(
        db,
        turn_system(
            f"{plan_system()}\n{extra_system}".strip(),
            compact_summary=compact_summary,
        ),
        json.dumps(user_payload, ensure_ascii=False),
        temperature=0,
        max_tokens=1024,
        timeout_s=12,
    )
    return parse_json_object(result.text), result.latency_ms


def run_plan(
    db: Session,
    *,
    text: str,
    parsed: SlashParse,
    history: list[dict[str, str]],
    prefs: dict,
    attachments: list[str],
    budget: TurnBudget,
    model_available: bool = True,
    compact_summary: str | None = None,
) -> PlanArtifact:
    """产出 PlanArtifact：斜杠模板 / LLM / 重试 / L0。"""

    def _finish(plan: PlanArtifact, *, slash: bool = False) -> PlanArtifact:
        """先按本轮意图注入短工具，再挂评测偏好，避免生图被沿用协议档/数据集。"""
        if slash:
            return _stamp_loop(_attach_prefs(plan, prefs))
        plan = inject_voiceclone_plan(db, plan, text=text, attachments=attachments)
        plan = inject_imagegen_plan(db, plan, text=text, attachments=attachments)
        return _stamp_loop(_attach_prefs(plan, prefs))

    if parsed.command == "compact":
        plan = plan_from_slash(parsed, prefs=prefs, attachments=attachments)
        return _finish(plan, slash=True)

    if parsed.is_slash:
        return PlanArtifact(
            intent="chat",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=[],
            delivery="text",
            budget={"max_tool_rounds": 0},
            notes="规划：未知会话控制命令。",
            source="slash",
        )

    if not model_available:
        plan = l0_plan(text, prefs=prefs)
        return _finish(plan)

    # 自然语言一律交给规划模型判定复杂度与 loop（chat / react / plan_solve）。
    # 关键词短路只作上游失败时的 L0 回退；斜杠仍 0 次模型。
    user_payload = {
        "text": text,
        "command": parsed.command or "",
        "args": parsed.args,
        "history": history,
        "prefs": prefs,
        "attachments": attachments,
    }
    try:
        raw, latency = _call_plan_model(
            db, user_payload, extra_system="", budget=budget, compact_summary=compact_summary
        )
        plan = sanitize_plan(raw, source="llm")
        plan.used_model = True
        plan.latency_ms = latency
        return _finish(plan)
    except AppError as exc:
        # 未配置协议档 / 上游失败：降级 L0，仍必须进复核
        if exc.code in {ErrorCode.VALIDATION, ErrorCode.UPSTREAM, ErrorCode.TIMEOUT}:
            agent_trace(f"规划模型不可用 code={exc.code.value}，降级 L0")
            plan = l0_plan(text, prefs=prefs)
            return _finish(plan)
        raise
    except Exception:
        agent_trace("规划 JSON 解析失败，准备重试")
    # 第 1 级：原样再要一次
    try:
        raw, latency = _call_plan_model(
            db,
            user_payload,
            extra_system=PLAN_RETRY_SUFFIX,
            budget=budget,
            compact_summary=compact_summary,
        )
        plan = sanitize_plan(raw, source="retry")
        plan.used_model = True
        plan.latency_ms = latency
        return _finish(plan)
    except AppError as exc:
        if exc.code in {ErrorCode.VALIDATION, ErrorCode.UPSTREAM, ErrorCode.TIMEOUT}:
            agent_trace(f"规划重试模型不可用 code={exc.code.value}，降级 L0")
            plan = l0_plan(text, prefs=prefs)
            return _finish(plan)
        raise
    except Exception:
        agent_trace("规划重试仍失败，降级 L0 规则意图")
        plan = l0_plan(text, prefs=prefs)
        return _finish(plan)


def _clarify_from_plan(plan: PlanArtifact, *, source: str = "replan") -> PlanArtifact:
    """补规划失败或预算不足时改判 clarify，不新开第二轮模型调用。"""
    extra = PlanArtifact(
        intent=plan.intent,
        skill_id=plan.skill_id,
        slots={
            "filled": dict(plan.slots.get("filled") or {}),
            "missing": list(plan.slots.get("missing") or []),
        },
        tools_needed=list(plan.tools_needed),
        delivery="clarify",
        budget=dict(plan.budget),
        notes=plan.notes or "补规划：槽位仍不齐，改为澄清。",
        used_model=plan.used_model,
        latency_ms=0,
        source=source,
        pref_thoughts=list(plan.pref_thoughts),
    )
    return extra


def run_replan(
    db: Session,
    *,
    text: str,
    parsed: SlashParse,
    history: list[dict[str, str]],
    prefs: dict,
    attachments: list[str],
    budget: TurnBudget,
    plan: PlanArtifact,
    observations: list[dict[str, Any]],
    compact_summary: str | None = None,
) -> PlanArtifact:
    """1 次补规划：观察摘要放入本轮 user JSON，不占 20 条消息窗口（HAR-ACT-04）。

    失败只降级为 clarify，禁止再开第二轮补规划。
    """
    if budget.remaining() <= 0:
        return _clarify_from_plan(plan)
    user_payload = {
        "text": text,
        "command": parsed.command or "",
        "args": parsed.args,
        "history": history,
        "prefs": prefs,
        "attachments": attachments,
        "observations": observations,
        "current_plan": plan.as_dict(),
    }
    try:
        raw, latency = _call_plan_model(
            db,
            user_payload,
            extra_system=REPLAN_JSON_SUFFIX,
            budget=budget,
            compact_summary=compact_summary,
        )
        extra = sanitize_plan({**plan.as_dict(), **raw}, source="replan")
        extra.used_model = True
        extra.latency_ms = latency
        extra.pref_thoughts = list(plan.pref_thoughts)
        return extra
    except AppError as exc:
        # 补规划失败一律澄清，不得把 INTERNAL 冒成 500 中断回合
        agent_trace(f"补规划模型失败 code={exc.code.value}，改判 clarify")
        return _clarify_from_plan(plan)
    except Exception:
        agent_trace("补规划 JSON 解析失败，改判 clarify")
        return _clarify_from_plan(plan)


def merge_replan(
    plan: PlanArtifact,
    extra: PlanArtifact,
    *,
    executed_tool_names: list[str],
) -> tuple[PlanArtifact, list[str]]:
    """把补规划合并进当前 plan；返回尚未执行的只读短工具队列。

    下单意图只允许继续 confirm 或改判 clarify；模型若返回 text/action，
    一律当澄清，避免随后误走闲聊交付。
    """
    plan.notes = extra.notes or plan.notes
    plan.latency_ms = extra.latency_ms
    plan.source = extra.source or plan.source
    extra_slots = extra.slots or {}
    if extra.delivery != "confirm":
        plan.delivery = "clarify"
        missing = extra_slots.get("missing")
        if missing:
            plan.slots["missing"] = list(missing)
        return plan, []
    plan.delivery = "confirm"
    filled = extra_slots.get("filled")
    if isinstance(filled, dict):
        plan.slots.setdefault("filled", {}).update(filled)
    if extra_slots.get("missing") is not None:
        plan.slots["missing"] = list(extra_slots.get("missing") or [])
    plan.tools_needed = list(extra.tools_needed)
    if extra.skill_id is not None:
        plan.skill_id = extra.skill_id
    # 出现长工具/未知工具时不续跑，留给 G4 reject，避免先出工具卡再报错
    if any(
        (not name) or name not in SHORT_TOOLS or is_long_tool(name) for name in extra.tools_needed
    ):
        return plan, []
    done = set(executed_tool_names)
    extra_tools = [
        name
        for name in extra.tools_needed
        if name not in done and name not in WRITE_TOOLS
    ]
    return plan, extra_tools
