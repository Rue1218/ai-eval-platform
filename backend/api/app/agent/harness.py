"""Harness：规划 → ReAct → 复核串联（HAR-FLOW / AGT-HRS-02/07）。

必须丢到 asyncio.Task 执行，收包循环不得 await 整轮。会话级 abort 为进程内
dict（HAR-NFR-08：单副本或粘性路由；多副本需外置，M1 不做）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Dataset, Message, ProtocolProfile, Task, User
from ..models import Session as AgentSession
from ..schemas import TaskCreate
from .context import history_for_plan, run_compact
from .defaults import (
    ACTIVE_STATUSES,
    MAX_MODEL_CALLS,
    NO_TITLE_COMMANDS,
    TERMINAL_STATUSES,
    TURN_WALL_CLOCK_S,
)
from .log import agent_trace
from .persona import chat_system
from .plan import PlanArtifact, TurnBudget, run_plan
from .prefs import load_prefs, save_prefs_from_spec
from .react import run_react
from .reflect import ReflectArtifact, maybe_model_check, run_gates
from .slash import assert_command_enabled, enabled_help_text, parse_slash, unknown_command_text

EmitFn = Callable[..., Awaitable[int]]


class HarnessAborted(Exception):
    """会话级 abort 或任务取消。"""


@dataclass
class SessionHarness:
    """单会话进行中的 Harness 回合。"""

    abort: asyncio.Event
    task: asyncio.Task | None = None


# 会话级 abort（进程内 dict）。部署前提：API 单副本，或网关按 session_id 粘性路由。
_HARNESS_BY_SESSION: dict[str, SessionHarness] = {}


def session_harness(session_id: str) -> SessionHarness | None:
    """读取当前会话的进行中回合。"""
    return _HARNESS_BY_SESSION.get(session_id)


def _clear_harness(session_id: str, task: asyncio.Task | None) -> None:
    current = _HARNESS_BY_SESSION.get(session_id)
    if current and (task is None or current.task is task):
        _HARNESS_BY_SESSION.pop(session_id, None)


def _check_abort(abort: asyncio.Event) -> None:
    if abort.is_set():
        raise HarnessAborted()


def deep_merge(base: dict, patch: dict) -> dict:
    """确认卡 patch 深合并：嵌套对象递归，数组整段替换。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


async def _emit_thought(
    emit: EmitFn,
    text: str,
    *,
    stage: str | None = None,
    skill_id: str | None = None,
    latency_ms: int | None = None,
) -> None:
    payload: dict[str, Any] = {"text": text}
    if stage:
        payload["stage"] = stage
    if skill_id:
        payload["skill_id"] = skill_id
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    await emit("thought", payload)


async def _deliver_sentence(
    db: Session,
    session_id: str,
    emit: EmitFn,
    text: str,
    *,
    task_id: str | None = None,
) -> None:
    """交付句：先 thought 事件，再写入 messages.role=assistant。"""
    await emit("thought", {"text": text}, task_id=task_id)
    db.add(Message(session_id=session_id, role="assistant", content=text))
    db.commit()


async def after_reflect(*_args: Any, **_kwargs: Any) -> None:
    """预留钩子 after_reflect：M2+ 扩展，M1 无 UI、无行为。"""
    return


async def after_ack(*_args: Any, **_kwargs: Any) -> None:
    """预留钩子 after_ack：M2+ 扩展，M1 无 UI、无行为。"""
    return


def _title_from_text(text: str) -> str:
    trimmed = text.strip()
    if len(trimmed) <= 40:
        return trimmed
    return trimmed[:40] + "…"


def _clarify_text(reflect: ReflectArtifact, plan: PlanArtifact) -> str:
    if reflect.reasons:
        return str(reflect.reasons[0])
    missing = plan.slots.get("missing") or []
    if missing:
        return f"还需要确认：{', '.join(missing)}。可以说具体协议档和数据集，或发送 /benchmark。"
    return "请再补充一下评测目标（协议档、数据集或 /benchmark）。"


async def _run_turn(
    db: Session,
    *,
    session: AgentSession,
    user: User,
    text: str,
    attachments: list[str],
    emit: EmitFn,
    abort: asyncio.Event,
) -> None:
    """单回合内部实现；调用前已检查 abort。"""
    _check_abort(abort)
    parsed = parse_slash(text)
    if parsed.command:
        assert_command_enabled(parsed.command)
        if parsed.command == "stop":
            # 无进行中回合时由外层处理；此处视为空操作
            await _deliver_sentence(db, session.id, emit, "当前没有正在生成的内容")
            return

    parsed_cmd = parsed.command or ""
    if session.title == "新会话" and text.strip() and parsed_cmd not in NO_TITLE_COMMANDS:
        session.title = _title_from_text(text)
        db.commit()

    prefs = load_prefs(db, user.id)
    history = history_for_plan(db, session)
    budget = TurnBudget(cap=MAX_MODEL_CALLS)

    # 未知斜杠
    if parsed.is_slash and not parsed.command:
        await _deliver_sentence(db, session.id, emit, unknown_command_text())
        return

    plan = await asyncio.to_thread(
        run_plan,
        db,
        text=text,
        parsed=parsed,
        history=history,
        prefs=prefs,
        attachments=attachments,
        budget=budget,
        model_available=True,
    )
    _check_abort(abort)
    notes = plan.notes or "规划中"
    if not notes.startswith("规划"):
        notes = f"规划：{notes}"
    await _emit_thought(
        emit,
        notes,
        stage="plan",
        skill_id=plan.skill_id,
        latency_ms=plan.latency_ms or None,
    )

    slash_fill_first = parsed.command in {"benchmark", "stress", "testcase", "rerun"}

    # 控制动作：/help /new 可不调工具
    if parsed.command == "help":
        plan.delivery = "text"
        plan.intent = "inspect"
        plan.tools_needed = []
    if parsed.command == "new":
        reflect = ReflectArtifact(verdict="pass", reasons=["控制动作 /new"], spec=None)
        await _emit_thought(emit, "复核：新建会话不入队", stage="reflect")
        await after_reflect(plan=plan, reflect=reflect)
        await _deliver_sentence(db, session.id, emit, "请使用左侧「新建会话」，随后会切换到新的空会话。")
        return
    if parsed.command == "help":
        await _emit_thought(emit, "复核：只读帮助，确认没有 create", stage="reflect")
        await _deliver_sentence(db, session.id, emit, enabled_help_text())
        return

    _check_abort(abort)
    react = await run_react(
        db,
        plan,
        user_id=user.id,
        emit=emit,
        check_abort=lambda: _check_abort(abort),
        slash_fill_first=slash_fill_first,
    )
    for note in react.pref_stale_notes:
        await _emit_thought(emit, note, stage="react")

    # 补规划：工具跑完仍缺槽，允许 1 次（HAR-ACT-04）
    missing = (plan.slots.get("missing") or []) if plan.intent in {"benchmark", "rag", "testcase"} else []
    if (
        missing
        and plan.tools_needed
        and budget.remaining() > 0
        and plan.delivery == "confirm"
        and parsed.command not in {"benchmark", "stress", "testcase"}
    ):
        _check_abort(abort)
        await _emit_thought(emit, "补规划：根据工具观察调整槽位", stage="plan")
        try:
            extra = await asyncio.to_thread(
                run_plan,
                db,
                text=text,
                parsed=parsed,
                history=history,
                prefs=prefs,
                attachments=attachments,
                budget=budget,
                model_available=True,
            )
            if extra.delivery == "clarify":
                plan.delivery = "clarify"
                plan.slots["missing"] = extra.slots.get("missing") or missing
                plan.notes = extra.notes
        except AppError:
            plan.delivery = "clarify"

    _check_abort(abort)
    reflect = run_gates(db, session=session, plan=plan, react=react, source="plan")
    # /compact 在规则通过后再执行（不计入 4 次硬顶）
    if plan.intent == "compact" and reflect.verdict == "pass":
        try:
            sentence, _old_m, _new_m = await asyncio.to_thread(run_compact, db, session)
        except AppError as exc:
            await emit("error", {"code": exc.code.value, "message": exc.message})
            await _deliver_sentence(db, session.id, emit, "上下文压缩失败，窗口未改动")
            return
        await _emit_thought(emit, "复核：保留近几条原文，不删历史、不覆盖人设", stage="reflect")
        await after_reflect(plan=plan, reflect=reflect)
        await _deliver_sentence(db, session.id, emit, sentence)
        return

    if parsed.command == "status":
        task = (
            db.query(Task)
            .filter(Task.session_id == session.id, Task.status.in_(ACTIVE_STATUSES))
            .first()
        )
        await _emit_thought(emit, "复核：只读状态，确认没有 create", stage="reflect")
        if task:
            await _deliver_sentence(
                db,
                session.id,
                emit,
                f"当前占槽：kind={task.kind} status={task.status} task_id={task.id}",
            )
        else:
            await _deliver_sentence(db, session.id, emit, "无活动任务")
        return

    if parsed.command == "cancel":
        task = (
            db.query(Task)
            .filter(Task.session_id == session.id, Task.status.in_(ACTIVE_STATUSES))
            .first()
        )
        await _emit_thought(emit, "复核：取消动作", stage="reflect")
        if not task:
            await _deliver_sentence(db, session.id, emit, "当前没有可取消的任务")
            return
        await _deliver_sentence(
            db,
            session.id,
            emit,
            f"将取消任务 {task.id[:8]}（{task.kind}/{task.status}）。请在界面确认对话框后提交取消。",
        )
        return

    if parsed.command == "profiles":
        count = 0
        for obs in react.observations:
            if obs.get("name") == "model.list" and obs.get("ok"):
                count = int((obs.get("data_summary") or {}).get("count") or 0)
        await _emit_thought(emit, "复核：只读列出协议档", stage="reflect")
        await _deliver_sentence(db, session.id, emit, f"当前共 {count} 个协议档。")
        return

    if parsed.command == "datasets":
        count = 0
        for obs in react.observations:
            if obs.get("name") == "dataset.list" and obs.get("ok"):
                count = int((obs.get("data_summary") or {}).get("count") or 0)
        await _emit_thought(emit, "复核：只读列出数据集", stage="reflect")
        await _deliver_sentence(db, session.id, emit, f"当前共 {count} 个数据集。" if count else "还没有数据集，请先到「数据集」页上传。")
        return

    if parsed.command == "rerun":
        last = (
            db.query(Task)
            .filter(Task.session_id == session.id, Task.status.in_(TERMINAL_STATUSES))
            .order_by(Task.finished_at.desc().nullslast(), Task.created_at.desc())
            .first()
        )
        if not last or not isinstance(last.config, dict):
            reflect = ReflectArtifact(verdict="clarify", reasons=["没有可重跑的终态任务"], spec=None)
        else:
            cfg = dict(last.config)
            cfg.pop("session_id", None)
            if cfg.get("kind") == "stress":
                reflect = ReflectArtifact(verdict="clarify", reasons=["不能把压测子任务直接重跑为 kind=stress"], spec=None)
            else:
                react.proposed_spec = cfg
                react.known_ids = list(
                    (cfg.get("profile_ids") or [])
                    + ([cfg["dataset_id"]] if cfg.get("dataset_id") else [])
                    + ([cfg["kb_id"]] if cfg.get("kb_id") else [])
                    + ([cfg["gold_qa_id"]] if cfg.get("gold_qa_id") else [])
                )
                plan.delivery = "confirm"
                plan.intent = str(cfg.get("kind") or "benchmark")
                reflect = run_gates(db, session=session, plan=plan, react=react, source="plan")

    # 规则优先；通过后模型核对（A2）
    if reflect.verdict == "pass":
        _check_abort(abort)
        reflect = await asyncio.to_thread(
            maybe_model_check, db, reflect, plan=plan, text=text, budget=budget
        )

    await after_reflect(plan=plan, reflect=reflect)

    reflect_note = "复核：" + ("；".join(reflect.reasons[:3]) if reflect.reasons else "已检查门禁")
    await _emit_thought(
        emit,
        reflect_note,
        stage="reflect",
        skill_id=plan.skill_id,
        latency_ms=reflect.latency_ms or None,
    )

    if reflect.verdict == "reject":
        code = reflect.error_code or ErrorCode.VALIDATION.value
        message = reflect.error_message or "无法完成本次请求"
        await emit("error", {"code": code, "message": message})
        await _deliver_sentence(db, session.id, emit, message)
        return

    if reflect.verdict == "clarify" or plan.delivery == "clarify":
        await _deliver_sentence(db, session.id, emit, _clarify_text(reflect, plan))
        return

    if plan.delivery == "confirm" and reflect.verdict == "pass" and reflect.spec:
        card = dict(reflect.spec)
        session.pending_confirm = card
        db.commit()
        await emit("confirm", card)
        return

    if plan.intent == "chat" or plan.delivery == "text":
        reply = await _chat_reply(db, text, history, budget)
        await _deliver_sentence(db, session.id, emit, reply)
        return

    await _deliver_sentence(db, session.id, emit, plan.notes or "已处理。")


async def _chat_reply(db: Session, text: str, history: list[dict[str, str]], budget: TurnBudget) -> str:
    """闲聊交付句：计入 4 次预算；失败回退短答。"""
    canned = (
        "你好！我是 AI 测试与评估平台的评测智能体。职责是协助你进行大模型质量评测、"
        "PRD 测试用例生成、知识库 RAG 评测与共享压测分析。\n\n"
        "请告诉我你的评测目标（例如：「对比两个模型的表现」或「生成登录模块测试用例」），"
        "我会先为你列出可用资产并组装确认卡，经你确认后再提交执行。"
    )
    if not budget.consume():
        return canned
    try:
        from ..llm import call_agent_model_detailed

        result = await asyncio.to_thread(
            call_agent_model_detailed,
            db,
            chat_system(),
            text if not history else f"最近对话：{history[-6:]}\n用户：{text}",
            temperature=0.4,
            max_tokens=2048,
            timeout_s=30,
        )
        return (result.text or "").strip() or canned
    except AppError:
        return canned
    except Exception as exc:
        agent_trace(f"闲聊回复内部异常 type={type(exc).__name__}")
        return canned


async def _harness_entry(
    *,
    session_id: str,
    user_id: str,
    text: str,
    attachments: list[str],
    emit_factory: Callable[[Session], EmitFn],
    abort: asyncio.Event,
) -> None:
    """Harness 任务入口：独立 DB 会话，墙钟 120s，结束后清理 registry。"""
    db = SessionLocal()
    task = asyncio.current_task()
    try:
        session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not session or not user:
            return
        emit = emit_factory(db)

        async def _body() -> None:
            await _run_turn(
                db,
                session=session,
                user=user,
                text=text,
                attachments=attachments,
                emit=emit,
                abort=abort,
            )

        await asyncio.wait_for(_body(), timeout=TURN_WALL_CLOCK_S)
    except TimeoutError:
        agent_trace(f"回合墙钟超时 session={session_id[:8]}")
        try:
            emit = emit_factory(db)
            await emit("error", {"code": ErrorCode.TIMEOUT.value, "message": "本轮超时，未出确认卡"})
            await _deliver_sentence(db, session_id, emit, "本轮超时，未出确认卡")
        except Exception as exc:  # noqa: BLE001
            agent_trace(f"超时交付内部异常 type={type(exc).__name__}")
    except HarnessAborted:
        try:
            emit = emit_factory(db)
            await _deliver_sentence(db, session_id, emit, "已停止生成")
        except Exception as exc:  # noqa: BLE001
            agent_trace(f"abort 交付内部异常 type={type(exc).__name__}")
    except asyncio.CancelledError:
        try:
            emit = emit_factory(db)
            await _deliver_sentence(db, session_id, emit, "已停止生成")
        except Exception as exc:  # noqa: BLE001
            agent_trace(f"cancel 交付内部异常 type={type(exc).__name__}")
        raise
    except AppError as exc:
        agent_trace(f"harness AppError code={exc.code.value}")
        try:
            emit = emit_factory(db)
            await emit("error", {"code": exc.code.value, "message": exc.message})
        except Exception:
            pass
    except Exception as exc:
        agent_trace(f"harness 内部异常 type={type(exc).__name__}")
        try:
            emit = emit_factory(db)
            await emit("error", {"code": ErrorCode.INTERNAL.value, "message": "消息处理失败，请稍后重试"})
        except Exception:
            pass
    finally:
        db.close()
        _clear_harness(session_id, task)


async def dispatch_user_message(
    *,
    session_id: str,
    user_id: str,
    text: str,
    attachments: list[str],
    emit_busy: EmitFn,
    emit_factory: Callable[[Session], EmitFn],
) -> None:
    """收包循环调用：/stop 置 abort；其它输入在已有回合时拒绝排队；否则 create_task。"""
    existing = _HARNESS_BY_SESSION.get(session_id)
    running = existing is not None and existing.task is not None and not existing.task.done()
    parsed = parse_slash(text)

    if running and existing:
        if parsed.command == "stop":
            existing.abort.set()
            if existing.task and not existing.task.done():
                existing.task.cancel()
            return
        await emit_busy("thought", {"text": "正在生成，先 /stop 或等本轮结束"})
        return

    if parsed.command == "stop" and not running:
        await emit_busy("thought", {"text": "当前没有正在生成的内容"})
        return

    handle = SessionHarness(abort=asyncio.Event())
    task = asyncio.create_task(
        _harness_entry(
            session_id=session_id,
            user_id=user_id,
            text=text,
            attachments=attachments,
            emit_factory=emit_factory,
            abort=handle.abort,
        )
    )
    handle.task = task
    _HARNESS_BY_SESSION[session_id] = handle


def _illegal_ack_fields(db: Session, spec: TaskCreate) -> list[str]:
    """ack patch 手填 ID 必须在库中真实存在（A3）。"""
    bad: list[str] = []
    if spec.profile_ids:
        found = {
            row.id
            for row in db.query(ProtocolProfile).filter(ProtocolProfile.id.in_(spec.profile_ids)).all()
        }
        if set(spec.profile_ids) - found:
            bad.append("profile_ids")
    if spec.dataset_id and not db.query(Dataset).filter(Dataset.id == spec.dataset_id).first():
        bad.append("dataset_id")
    return bad


async def handle_confirm_ack(
    db: Session,
    *,
    session: AgentSession,
    user: User,
    ok: bool,
    patch: dict | None,
    emit: EmitFn,
) -> None:
    """确认卡回执。ok=true 但校验失败：error + 卡保留（A1）。"""
    base = session.pending_confirm if isinstance(session.pending_confirm, dict) else None

    if not ok:
        session.pending_confirm = None
        db.commit()
        await _deliver_sentence(db, session.id, emit, "已取消本次确认，不会创建任务。需要调整目标可以继续说。")
        return

    if base is None:
        await emit("error", {"code": ErrorCode.VALIDATION.value, "message": "没有待确认的评测单，请先发送目标重新生成。"})
        return

    merged = deep_merge(deepcopy(base), patch or {})
    if merged.get("kind") == "stress":
        await emit(
            "error",
            {"code": ErrorCode.VALIDATION.value, "message": "压测由质量任务勾选「先评后压」派生，不能单独下单"},
        )
        return

    occupied = (
        db.query(Task)
        .filter(Task.session_id == session.id, Task.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if occupied:
        await emit(
            "error",
            {"code": ErrorCode.CONCURRENCY.value, "message": "当前会话已有未完成任务，请等待其结束后再下单。"},
        )
        return

    try:
        spec = TaskCreate.model_validate(merged)
    except Exception:
        await emit(
            "error",
            {"code": ErrorCode.VALIDATION.value, "message": "评测单字段不完整或非法，请补全后重新确认。"},
        )
        return

    illegal = _illegal_ack_fields(db, spec)
    if illegal:
        # A1 / A3：手填非法 ID → error 指出字段，pending_confirm 不清空
        await emit(
            "error",
            {
                "code": ErrorCode.VALIDATION.value,
                "message": f"非法字段: {', '.join(illegal)}",
            },
        )
        return

    task = Task(
        kind=spec.kind,
        session_id=session.id,
        config=spec.snapshot(),
        progress={"done": 0, "total": 0, "message": "任务已入队"},
        created_by=user.id,
        status="queued",
    )
    db.add(task)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_create",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
        )
    )
    session.pending_confirm = None
    try:
        db.commit()
        db.refresh(task)
    except IntegrityError:
        db.rollback()
        await emit(
            "error",
            {"code": ErrorCode.CONCURRENCY.value, "message": "当前会话已有未完成任务，请勿重复提交。"},
        )
        return
    save_prefs_from_spec(db, user.id, spec.snapshot())

    await emit("tool_call", {"name": "task.create", "arguments": spec.snapshot()}, task_id=task.id)
    await emit(
        "tool_result",
        {"name": "task.create", "ok": True, "data": {"task_id": task.id, "status": "queued"}, "latency_ms": 0},
        task_id=task.id,
    )
    await _deliver_sentence(
        db,
        session.id,
        emit,
        "任务已入队（queued），Worker 将异步执行并回推进度与报告。",
        task_id=task.id,
    )
    await emit(
        "progress",
        {"percent": 0, "done": 0, "total": 1, "message": "任务已入队，等待 Worker 领取"},
        task_id=task.id,
    )
    await after_ack(task_id=task.id, spec=spec.snapshot())


async def handle_cancel_task(
    db: Session,
    *,
    session: AgentSession,
    user: User,
    task_id: str,
    emit: EmitFn,
) -> None:
    """取消当前成员的非终态任务，与 REST cancel 语义一致。"""
    task = db.query(Task).filter(Task.id == task_id, Task.created_by == user.id).first()
    if not task:
        await emit("error", {"code": ErrorCode.NOT_FOUND.value, "message": "任务不存在"})
        return
    if task.status in TERMINAL_STATUSES:
        await emit("error", {"code": ErrorCode.VALIDATION.value, "message": "任务已结束"}, task_id=task.id)
        return
    now = datetime.now(UTC)
    task.cancel_requested_at = now
    task.status = "cancelled"
    task.finished_at = now
    task.progress = {**(task.progress or {}), "message": "任务已取消"}
    db.add(
        AuditLog(
            user_id=user.id,
            action="task_cancel",
            target_type="task",
            target_id=task.id,
            detail={"kind": task.kind},
        )
    )
    db.commit()
    await _deliver_sentence(db, session.id, emit, "已收到取消请求，任务状态已更新为 cancelled。")
