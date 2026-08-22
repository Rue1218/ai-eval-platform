"""复核阶段：确定性规则门禁 + 可选模型核对（HAR-RFL）。

规则失败立即 clarify/reject，不得再调模型放行。模型不得把 reject 改成 pass。
核对调用失败不阻断交付。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.harness.orchestration.plan_runtime import PlanArtifact, TurnBudget, parse_json_object
from app.harness.orchestration.react_adapter import ReactArtifact, _missing_for_kind

from ..errors import AppError, ErrorCode
from ..models import Session as AgentSession
from ..models import Task
from .defaults import ACTIVE_STATUSES, SHORT_TOOLS, is_long_tool
from .log import agent_trace
from .persona import reflect_check_system, turn_system


@dataclass
class ReflectArtifact:
    """复核产物。verdict 三态冻结。"""

    verdict: str
    reasons: list[str] = field(default_factory=list)
    spec: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reasons": list(self.reasons), "spec": self.spec}


def _occupied_task(db: Session, session_id: str) -> Task | None:
    return (
        db.query(Task)
        .filter(Task.session_id == session_id, Task.status.in_(ACTIVE_STATUSES))
        .first()
    )


def run_gates(
    db: Session,
    *,
    session: AgentSession,
    plan: PlanArtifact,
    react: ReactArtifact,
    source: str = "plan",
) -> ReflectArtifact:
    """0 次模型调用的硬门禁（G1–G9）。``source`` 为 plan 或 ack_patch。"""
    reasons: list[str] = []
    spec = react.proposed_spec
    tools = list(plan.tools_needed)

    # G4 / G9：长工具与白名单
    for name in tools:
        if is_long_tool(name):
            return ReflectArtifact(
                verdict="reject",
                reasons=[f"禁止在对话进程执行长工具 {name}"],
                spec=None,
                error_code=ErrorCode.VALIDATION.value,
                error_message=f"「{name}」是长任务，只能入队后由 Worker 执行",
            )
        if name not in SHORT_TOOLS:
            return ReflectArtifact(
                verdict="reject",
                reasons=[f"工具不在短工具清单: {name}"],
                spec=None,
                error_code=ErrorCode.VALIDATION.value,
                error_message="只允许调用系统提供的短工具",
            )

    # G8：不执行任意代码、不改人设（规划 notes / tools 已由白名单约束）
    text_blob = json.dumps(plan.as_dict(), ensure_ascii=False)
    if any(k in text_blob.lower() for k in ("os.system", "subprocess", "eval(", "改人设", "跳过确认")):
        return ReflectArtifact(
            verdict="reject",
            reasons=["触达安全红线"],
            spec=None,
            error_code=ErrorCode.VALIDATION.value,
            error_message="拒绝执行该请求",
        )

    # 闲聊 / 控制 / 只读：确认没有 create
    if plan.delivery in {"text", "action", "clarify"} and plan.intent in {
        "chat",
        "inspect",
        "compact",
        "cancel",
        "report",
    }:
        if any(obs.get("name") == "task.create" and obs.get("ok") for obs in react.observations):
            return ReflectArtifact(verdict="reject", reasons=["闲聊路径不得 create"], spec=None)
        return ReflectArtifact(verdict="pass", reasons=["确认没有 create"], spec=None)

    # G7：Agent 对话不得发出 kind=stress 确认卡
    if spec and spec.get("kind") == "stress":
        return ReflectArtifact(
            verdict="reject",
            reasons=["禁止 kind=stress 确认卡"],
            spec=None,
            error_code=ErrorCode.VALIDATION.value,
            error_message="压测由质量任务勾选「先评后压」派生，不能单独下单",
        )

    want_confirm = plan.delivery == "confirm" or (
        plan.source == "slash" and plan.intent in {"benchmark", "rag", "testcase", "rerun"}
    )

    # G5：占槽禁新卡
    occupied = _occupied_task(db, session.id)
    if occupied and want_confirm:
        return ReflectArtifact(
            verdict="clarify",
            reasons=[
                f"当前会话已有未完成任务 kind={occupied.kind} status={occupied.status}，请 /status 或 /cancel"
            ],
            spec=None,
            error_code=ErrorCode.CONCURRENCY.value,
            error_message="当前会话已有未完成任务，确认已禁用",
        )

    # 未启用能力：rag / report 在 M1 拒绝并说明，禁止假成功
    if plan.intent == "rag" or (spec and spec.get("kind") == "rag"):
        return ReflectArtifact(
            verdict="reject",
            reasons=["RAG 里程碑未到"],
            spec=None,
            error_code=ErrorCode.VALIDATION.value,
            error_message="将在知识库阶段启用",
        )
    if plan.intent == "report":
        return ReflectArtifact(
            verdict="reject",
            reasons=["报告解读未启用"],
            spec=None,
            error_code=ErrorCode.VALIDATION.value,
            error_message="报告解读能力将在 M4 接入，当前请先到评测报告页查看",
        )

    if not want_confirm:
        return ReflectArtifact(verdict="pass", reasons=["非下单路径"], spec=None)

    if not spec:
        return ReflectArtifact(verdict="clarify", reasons=["尚未组出确认卡字段，请补充协议档与数据集"], spec=None)

    # G1：一单一 kind
    kind = spec.get("kind")
    if kind not in {"benchmark", "rag", "testcase"}:
        return ReflectArtifact(verdict="clarify", reasons=["kind 非法或不唯一"], spec=None)
    if kind == "benchmark" and (spec.get("kb_id") or spec.get("gold_qa_id")):
        return ReflectArtifact(verdict="clarify", reasons=["禁止 Benchmark 与 RAG 混在一张卡"], spec=None)

    # G2：必填槽位
    missing = _missing_for_kind(spec)
    if missing:
        return ReflectArtifact(
            verdict="clarify",
            reasons=[f"缺少必填槽位: {', '.join(missing)}"],
            spec=None,
        )
    if kind == "benchmark":
        pids = spec.get("profile_ids") or []
        if not 1 <= len(pids) <= 5:
            return ReflectArtifact(verdict="clarify", reasons=["profile_ids 需要 1–5 个"], spec=None)

    # G3：资产 ID 可溯源
    known = set(react.known_ids)
    illegal: list[str] = []
    for pid in spec.get("profile_ids") or []:
        if pid not in known:
            illegal.append("profile_ids")
            break
    if spec.get("dataset_id") and spec["dataset_id"] not in known:
        illegal.append("dataset_id")
    if spec.get("kb_id") and spec["kb_id"] not in known:
        illegal.append("kb_id")
    if spec.get("gold_qa_id") and spec["gold_qa_id"] not in known:
        illegal.append("gold_qa_id")
    if illegal:
        # 规划/工具链路 → clarify；ack patch 手填 → 由调用方改判 error
        if source == "ack_patch":
            return ReflectArtifact(
                verdict="reject",
                reasons=[f"手填资产不存在: {', '.join(illegal)}"],
                spec=None,
                error_code=ErrorCode.VALIDATION.value,
                error_message=f"非法字段: {', '.join(illegal)}",
            )
        return ReflectArtifact(
            verdict="clarify",
            reasons=["资产不存在，请重新选择"],
            spec=None,
        )

    reasons.append("kind 唯一")
    reasons.append("必填槽位已齐")
    reasons.append("资产 ID 来自本轮工具结果")
    if not occupied:
        reasons.append("未占槽")
    return ReflectArtifact(verdict="pass", reasons=reasons, spec=spec)


def maybe_model_check(
    db: Session,
    artifact: ReflectArtifact,
    *,
    plan: PlanArtifact,
    text: str,
    budget: TurnBudget,
    compact_summary: str | None = None,
    observations: list[dict[str, Any]] | None = None,
) -> ReflectArtifact:
    """规则 pass 后 1 次「是否符合用户目标」。失败不阻断；不得把 reject 改成 pass。

    仅确认卡需要模型核对。闲聊 / 只读斜杠由规则门禁「确认没有 create」即可，
    再调一次上游会把「你好」拖到几十秒，且核对结果对确定性斜杠本来就会被丢弃。
    """
    if artifact.verdict != "pass":
        return artifact
    if plan.delivery != "confirm":
        return artifact
    if not budget.consume():
        return artifact
    try:
        payload = {
            "user_text": text,
            "plan": plan.as_dict(),
            "verdict": artifact.verdict,
            "spec": artifact.spec,
            # 观察摘要不占 20 条消息窗口，只进本轮核对 user JSON（HAR-ACT-01）
            "observations": observations or [],
        }
        from ..llm import call_agent_model_detailed

        result = call_agent_model_detailed(
            db,
            turn_system(
                reflect_check_system(),
                skill_id=plan.skill_id,
                compact_summary=compact_summary,
            ),
            json.dumps(payload, ensure_ascii=False),
            temperature=0,
            max_tokens=512,
            timeout_s=12,
        )
        artifact.latency_ms = result.latency_ms
        parsed = parse_json_object(result.text)
        suggested = str(parsed.get("verdict") or "").strip().lower()
        if suggested == "clarify":
            reasons = parsed.get("reasons") if isinstance(parsed.get("reasons"), list) else ["请补充评测目标"]
            artifact.verdict = "clarify"
            artifact.reasons = [str(r) for r in reasons]
            artifact.spec = None
            agent_trace("复核核对建议 clarify")
        elif suggested == "reject":
            # 模型不得单方面放行，但可以把 pass 降为 clarify 以免越权下单
            artifact.verdict = "clarify"
            artifact.spec = None
            artifact.reasons = ["复核认为目标仍不清晰"]
        # suggested pass 或非法值：保持规则结果
    except AppError as exc:
        agent_trace(f"复核核对失败 code={exc.code.value}，按规则结果交付")
    except Exception as exc:
        agent_trace(f"复核核对内部异常 type={type(exc).__name__}")
    return artifact
