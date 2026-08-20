"""规划阶段：PlanArtifact 解析、斜杠模板、LLM 调用与 L0 降级（HAR-PLAN）。"""

from __future__ import annotations

import json
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
from .log import agent_trace
from .persona import PLAN_RETRY_SUFFIX, REPLAN_JSON_SUFFIX, plan_system, turn_system
from .slash import SlashParse


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

    return PlanArtifact(
        intent=intent,
        skill_id=skill_id,
        slots=slots,
        tools_needed=tools,
        delivery=delivery,
        budget={"max_tool_rounds": rounds},
        notes=notes,
        source=source,
    )


# 高置信闲聊提示（不含「其它 → chat」兜底）。用于跳过规划模型，把预算留给流式回复。
CHAT_HINTS = ("你好", "您好", "介绍", "你是谁", "天气", "谢谢", "闲聊", "随便聊聊", "hello", "hi ")
# 与评测关键词重叠时不得当闲聊，避免「你好，帮我评一下」跳过规划
EVAL_BLOCK_HINTS = (
    "评测",
    "评估",
    "对比",
    "benchmark",
    "跑分",
    "打分",
    "测试模型",
    "模型质量",
    "评一下",
    "帮我评",
)


def is_smalltalk(text: str) -> bool:
    """问候/闲聊关键词且无评测关键词。不含含糊句的 chat 兜底。"""
    raw = text or ""
    lowered = raw.lower()
    if any(k in raw for k in EVAL_BLOCK_HINTS):
        return False
    return any(k.lower() in lowered for k in CHAT_HINTS)


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
    if any(k in lowered for k in ("benchmark", "评测", "评估", "对比", "跑分", "打分", "测试模型", "模型质量", "评一下", "帮我评")):
        return "benchmark", False
    # HAR-PLAN-05：其它 → benchmark（缺槽走 clarify，不出假卡）
    if raw.startswith("/"):
        return "benchmark", False
    return "chat", False


def l0_plan(text: str, *, prefs: dict | None = None) -> PlanArtifact:
    """L0 降级产物形状（评审默认方案 D1）。仍必须进入复核。"""
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
    return PlanArtifact(
        intent=intent,
        skill_id=skill_id,
        slots={"filled": filled, "missing": missing},
        tools_needed=tools,
        delivery=delivery,
        budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
        notes=notes,
        source="l0",
    )


def plan_from_slash(parsed: SlashParse, *, prefs: dict | None, attachments: list[str]) -> PlanArtifact:
    """斜杠已绑定 intent：0 次模型，模板生成规划短句（HAR-PLAN-04）。"""
    command = parsed.command or ""
    args = parsed.args
    prefs = prefs or {}
    last_kind = prefs.get("last_kind")

    if command == "benchmark":
        return PlanArtifact(
            intent="benchmark",
            skill_id="skill-benchmark",
            slots={"filled": {"kind": "benchmark", "with_stress": False}, "missing": ["profile_ids", "dataset_id"]},
            tools_needed=["model.list", "dataset.list"],
            delivery="confirm",
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes="规划：基准评测。先列出协议档和数据集，再组确认卡。",
            source="slash",
        )
    if command == "stress":
        intent = "rag" if last_kind == "rag" else "benchmark"
        return PlanArtifact(
            intent=intent,
            skill_id="skill-stress",
            slots={
                "filled": {"kind": intent, "with_stress": True},
                "missing": list(REQUIRED_SLOTS[intent]) + ["stress"],
            },
            tools_needed=list(DEFAULT_TOOLS_BY_INTENT[intent]),
            delivery="confirm",
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes="规划：先评后压。确认卡 kind 仍为质量任务。",
            source="slash",
        )
    if command == "testcase":
        missing = [] if attachments or args else ["case_source"]
        filled: dict[str, Any] = {"kind": "testcase"}
        if args:
            filled["case_source"] = {"text": args}
            missing = []
        return PlanArtifact(
            intent="testcase",
            skill_id="skill-testcase",
            slots={"filled": filled, "missing": missing},
            tools_needed=[],
            delivery="confirm" if not missing else "clarify",
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes="规划：用例生成。请确认 PRD / 需求文本。",
            source="slash",
        )
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
    if command in {"cancel", "rerun", "new", "help"}:
        notes_map = {
            "cancel": "规划：取消本会话未完成任务。",
            "rerun": "规划：拷贝最近任务配置，仍须确认卡。",
            "new": "规划：新建空会话。",
            "help": "规划：列出已启用命令。",
        }
        tools = ["task.get"] if command in {"cancel", "rerun"} else []
        delivery = "confirm" if command == "rerun" else "action" if command != "help" else "text"
        return PlanArtifact(
            intent="cancel" if command == "cancel" else "rerun" if command == "rerun" else "inspect",
            skill_id="skill-benchmark" if command == "rerun" else None,
            slots={"filled": {}, "missing": []},
            tools_needed=tools,
            delivery=delivery,
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes=notes_map[command],
            source="slash",
        )
    if command in {"status", "profiles", "datasets"}:
        tools = {
            "status": ["task.get"],
            "profiles": ["model.list"],
            "datasets": ["dataset.list"],
        }[command]
        return PlanArtifact(
            intent="inspect",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=tools,
            delivery="text",
            budget={"max_tool_rounds": DEFAULT_TOOL_ROUNDS},
            notes=f"规划：只读查询 /{command}。",
            source="slash",
        )
    # 未知命令：text 交付
    return PlanArtifact(
        intent="inspect",
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
    if parsed.command and parsed.command in {
        "benchmark",
        "testcase",
        "stress",
        "compact",
        "cancel",
        "rerun",
        "new",
        "help",
        "status",
        "profiles",
        "datasets",
        "stop",
    }:
        plan = plan_from_slash(parsed, prefs=prefs, attachments=attachments)
        return _attach_prefs(plan, prefs)

    if parsed.is_slash and parsed.command not in {
        "benchmark",
        "testcase",
        "stress",
        "compact",
        "cancel",
        "rerun",
        "new",
        "help",
        "status",
        "profiles",
        "datasets",
        "stop",
        "rag",
        "kb",
        "report",
    }:
        return PlanArtifact(
            intent="inspect",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=[],
            delivery="action",
            budget={"max_tool_rounds": 0},
            notes="规划：未知命令。",
            source="slash",
        )

    if not model_available:
        plan = l0_plan(text, prefs=prefs)
        return _attach_prefs(plan, prefs)

    # 「你好」等高置信闲聊：L0 定位即可，禁止再串行打规划模型（否则问候要等 2～3 次上游）。
    if is_smalltalk(text):
        plan = l0_plan(text, prefs=prefs)
        return _attach_prefs(plan, prefs)

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
        return _attach_prefs(plan, prefs)
    except AppError as exc:
        # 未配置协议档 / 上游失败：降级 L0，仍必须进复核
        if exc.code in {ErrorCode.VALIDATION, ErrorCode.UPSTREAM, ErrorCode.TIMEOUT}:
            agent_trace(f"规划模型不可用 code={exc.code.value}，降级 L0")
            plan = l0_plan(text, prefs=prefs)
            return _attach_prefs(plan, prefs)
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
        return _attach_prefs(plan, prefs)
    except AppError as exc:
        if exc.code in {ErrorCode.VALIDATION, ErrorCode.UPSTREAM, ErrorCode.TIMEOUT}:
            agent_trace(f"规划重试模型不可用 code={exc.code.value}，降级 L0")
            plan = l0_plan(text, prefs=prefs)
            return _attach_prefs(plan, prefs)
        raise
    except Exception:
        agent_trace("规划重试仍失败，降级 L0 规则意图")
        plan = l0_plan(text, prefs=prefs)
        return _attach_prefs(plan, prefs)


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

