"""结构化任务状态机契约（Session Task State / Blackboard）。

将 Agent 的多步任务认知体系从非结构化聊天记录和静态步骤列表升级为
「动态结构化任务状态机」。包含终局目标、假设验证、确立事实、已排除方向、
关键信息缺口（missing_info）与交付门禁（can_deliver）。

全部契约 frozen + JSON 可序列化（PG 检查点与 WebSocket 兼容），禁止嵌 Callable、
WebSocket、DB Session；支持与现有 PlanArtifact 双向兼容与平滑演进。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

TaskPhase = Literal["exploring", "verifying", "converging", "completed", "blocked"]


@dataclass(frozen=True, slots=True)
class RejectedHypothesis:
    """已证伪的假设与排查记录（防止模型反复踩坑或重提旧假设）。"""

    hypothesis: str  # 已被证伪的假设描述
    reason: str  # 证伪原因 / 依据
    evidence_ref: str = ""  # 关联证据（如日志片断、文件路径或调用记录）


@dataclass(frozen=True, slots=True)
class FailedStep:
    """失败步骤与原因记录。"""

    step: str  # 失败步骤标题
    reason: str  # 失败根因
    repair_hint: str = ""  # 修复建议


@dataclass(frozen=True, slots=True)
class TaskSessionState:
    """结构化任务状态机契约（认知黑板）。"""

    protocol: Literal["task_state"] = "task_state"
    version: Literal["v1"] = "v1"

    # 1. 终局目标（抗注意力漂移锚点）
    goal: str = ""
    phase: TaskPhase = "exploring"

    # 2. 步骤推进链
    completed_steps: tuple[str, ...] = field(default_factory=tuple)
    current_step: str = ""
    next_actions: tuple[str, ...] = field(default_factory=tuple)
    failed_steps: tuple[FailedStep, ...] = field(default_factory=tuple)

    # 3. 认知与事实库（确立事实与排除假设）
    current_hypothesis: str = ""
    confirmed_facts: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)
    rejected_hypotheses: tuple[RejectedHypothesis, ...] = field(default_factory=tuple)

    # 4. 闭环门禁（最关键的防假收尾字段）
    missing_info: tuple[str, ...] = field(default_factory=tuple)
    can_deliver: bool = False

    # 5. 补充说明与阻塞原因
    blocked_reason: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        """转换为 json.dumps 安全的字典结构。"""
        return {
            "protocol": self.protocol,
            "version": self.version,
            "goal": self.goal,
            "phase": self.phase,
            "completed_steps": list(self.completed_steps),
            "current_step": self.current_step,
            "next_actions": list(self.next_actions),
            "failed_steps": [
                {
                    "step": item.step,
                    "reason": item.reason,
                    "repair_hint": item.repair_hint,
                }
                for item in self.failed_steps
            ],
            "current_hypothesis": self.current_hypothesis,
            "confirmed_facts": list(self.confirmed_facts),
            "evidence": list(self.evidence),
            "rejected_hypotheses": [
                {
                    "hypothesis": item.hypothesis,
                    "reason": item.reason,
                    "evidence_ref": item.evidence_ref,
                }
                for item in self.rejected_hypotheses
            ],
            "missing_info": list(self.missing_info),
            "can_deliver": self.can_deliver,
            "blocked_reason": self.blocked_reason,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskSessionState:
        """从字典安全重建不可变 TaskSessionState，具备容错默认值。"""
        raw = dict(data or {})

        def str_tuple(raw_val: object) -> tuple[str, ...]:
            if isinstance(raw_val, list | tuple):
                return tuple(str(x) for x in raw_val if str(x).strip())
            return ()

        failed_steps: list[FailedStep] = []
        for item in raw.get("failed_steps") or ():
            if isinstance(item, Mapping):
                failed_steps.append(
                    FailedStep(
                        step=str(item.get("step") or ""),
                        reason=str(item.get("reason") or ""),
                        repair_hint=str(item.get("repair_hint") or ""),
                    )
                )
            elif isinstance(item, FailedStep):
                failed_steps.append(item)

        rejected_hypotheses: list[RejectedHypothesis] = []
        for item in raw.get("rejected_hypotheses") or ():
            if isinstance(item, Mapping):
                rejected_hypotheses.append(
                    RejectedHypothesis(
                        hypothesis=str(item.get("hypothesis") or ""),
                        reason=str(item.get("reason") or ""),
                        evidence_ref=str(item.get("evidence_ref") or ""),
                    )
                )
            elif isinstance(item, RejectedHypothesis):
                rejected_hypotheses.append(item)

        phase = str(raw.get("phase") or "exploring")
        if phase not in {"exploring", "verifying", "converging", "completed", "blocked"}:
            phase = "exploring"

        missing_info = str_tuple(raw.get("missing_info"))
        can_deliver = bool(raw.get("can_deliver"))
        # 守卫：如果存在明确的 missing_info，强制不允许判定为可交付
        if missing_info and can_deliver:
            can_deliver = False

        return cls(
            protocol="task_state",
            version="v1",
            goal=str(raw.get("goal") or ""),
            phase=phase,  # type: ignore[arg-type]
            completed_steps=str_tuple(raw.get("completed_steps")),
            current_step=str(raw.get("current_step") or ""),
            next_actions=str_tuple(raw.get("next_actions")),
            failed_steps=tuple(failed_steps),
            current_hypothesis=str(raw.get("current_hypothesis") or ""),
            confirmed_facts=str_tuple(raw.get("confirmed_facts")),
            evidence=str_tuple(raw.get("evidence")),
            rejected_hypotheses=tuple(rejected_hypotheses),
            missing_info=missing_info,
            can_deliver=can_deliver,
            blocked_reason=str(raw.get("blocked_reason") or ""),
            notes=str(raw.get("notes") or ""),
        )


def evolve_task_state(
    current: TaskSessionState,
    observations: list[object] | tuple[object, ...],
) -> TaskSessionState:
    """根据最新累积的 Observation 列表驱动结构化任务状态机演进。"""
    if not observations:
        return current

    confirmed_facts = list(current.confirmed_facts)
    evidence = list(current.evidence)
    failed_steps = list(current.failed_steps)
    rejected_hypotheses = list(current.rejected_hypotheses)
    completed_steps = list(current.completed_steps)
    missing_info = list(current.missing_info)
    next_actions = list(current.next_actions)
    current_step = current.current_step

    for obs in observations:
        tool = str(getattr(obs, "tool", "") or "")
        if not tool or tool.startswith("__"):
            continue
        ok = bool(getattr(obs, "ok", False))
        text = str(getattr(obs, "text", "") or "").strip()
        source = str(getattr(obs, "source", "") or "").strip()

        if ok:
            fact = f"通过 {tool} 成功获取数据：{text[:120]}" if text else f"工具 {tool} 执行成功"
            if fact not in confirmed_facts:
                confirmed_facts.append(fact)
            if source and source not in evidence:
                evidence.append(source)

            if current_step and current_step not in completed_steps:
                completed_steps.append(current_step)
                for item in list(missing_info):
                    if item == current_step or tool in item:
                        missing_info.remove(item)
                if next_actions:
                    current_step = next_actions.pop(0)
                else:
                    current_step = ""
        else:
            repair_hint = str(getattr(obs, "repair_hint", "") or "")
            fail_step = FailedStep(step=tool, reason=text[:160], repair_hint=repair_hint)
            if fail_step not in failed_steps:
                failed_steps.append(fail_step)

            if current.current_hypothesis:
                rej = RejectedHypothesis(
                    hypothesis=current.current_hypothesis,
                    reason=f"{tool} 执行未达预期：{text[:120]}",
                    evidence_ref=source,
                )
                if rej not in rejected_hypotheses:
                    rejected_hypotheses.append(rej)

    can_deliver = len(missing_info) == 0 and (len(completed_steps) > 0 or not current.missing_info)
    phase: TaskPhase = (
        "converging"
        if can_deliver
        else ("verifying" if current.current_hypothesis else "exploring")
    )

    return TaskSessionState(
        protocol="task_state",
        version="v1",
        goal=current.goal,
        phase=phase,
        completed_steps=tuple(completed_steps),
        current_step=current_step,
        next_actions=tuple(next_actions),
        failed_steps=tuple(failed_steps),
        current_hypothesis=current.current_hypothesis,
        confirmed_facts=tuple(confirmed_facts),
        evidence=tuple(evidence),
        rejected_hypotheses=tuple(rejected_hypotheses),
        missing_info=tuple(missing_info),
        can_deliver=can_deliver,
        blocked_reason=current.blocked_reason,
        notes=current.notes,
    )

