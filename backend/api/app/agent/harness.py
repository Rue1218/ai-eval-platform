"""Harness：斜杠直达；自然语言走同一轮 CoT（流式思考链 → 工具或回复）。

必须丢到 asyncio.Task 执行，收包循环不得 await 整轮。会话级 abort 为进程内
dict（HAR-NFR-08：单副本或粘性路由；多副本需外置，M1 不做）。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.trace import TraceContext, current_trace, using_trace
from app.harness.contracts.turn import TurnStatus
from app.harness.feedback.publisher import publisher
from app.harness.memory.runtime import append_persisted_conversation_message
from app.harness.orchestration.budgets import wall_clock_s
from app.harness.orchestration.streaming import begin_finalizing_delivery

from ..db import SessionLocal
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Dataset, Message, ProtocolProfile, Task, TaskEvent, User
from ..models import Session as AgentSession
from ..schemas import TaskCreate
from .context import history_for_plan, run_compact
from .defaults import (
    ACTIVE_STATUSES,
    MAX_MODEL_CALLS,
    NO_TITLE_COMMANDS,
    STREAM_EMIT_WAIT_S,
    STREAM_TIMEOUT_S,
    TERMINAL_STATUSES,
)
from .log import agent_exception, agent_trace
from .persona import chat_system, turn_system
from .plan import AUDIO_CLARIFY_RE, PlanArtifact, TurnBudget, merge_replan, run_plan, run_replan
from .prefs import load_prefs, save_prefs_from_spec
from .react import run_react
from .reflect import ReflectArtifact, maybe_model_check, run_gates
from .slash import (
    assert_command_enabled,
    enabled_help_text,
    is_unknown_slash,
    parse_slash,
    unknown_command_text,
)
from .turn_mode import (
    TurnMode,
    allows_model_check,
    allows_replan,
    emits_stage_thoughts,
    resolve_turn_mode,
    uses_react_llm,
)
from .voiceclone import VOICECLONE_CLARIFY_RE

EmitFn = Callable[..., Awaitable[int]]


class HarnessAborted(Exception):
    """会话级 abort 或任务取消。"""


@dataclass
class SessionHarness:
    """单会话进行中的 Harness 回合。"""

    # 当前回合的发言人；共享会话中只有该成员可执行 /stop。
    user_id: str
    abort: asyncio.Event
    stop: threading.Event
    cancel: CancellationToken
    trace: TraceContext
    task: asyncio.Task | None = None


# 会话级 abort（进程内 dict）。部署前提：API 单副本，或网关按 session_id 粘性路由。
# 阶段 2 不把该 registry 迁 Redis（扩副本议题，非本阶段）。
_HARNESS_BY_SESSION: dict[str, SessionHarness] = {}
# 保护 registry 的 check-and-set，避免共享会话两人同时开两轮 Harness
_HARNESS_REGISTRY_LOCK = asyncio.Lock()
# 回合开始时间（wall-clock）：_harness_entry 启动时写入，_deliver_sentence 用它计算
# 回复耗时 latency_ms。以 contextvar 传播，避免把 round_started_at 参数串进十几个调用点。
_ROUND_STARTED_AT: ContextVar[datetime | None] = ContextVar("round_started_at", default=None)

# 斜杠控制/只读命令的交付句由规则决定；核对不得把 /help 等改成澄清问句
_DETERMINISTIC_SLASH = frozenset(
    {"help", "new", "status", "cancel", "profiles", "datasets", "compact"}
)


def should_emit_stage_thoughts(
    intent: str,
    command: str | None,
    mode: TurnMode | None = None,
) -> bool:
    """是否把规划/复核刷成思考卡。

    闲聊、生图 ReAct、/help 等只交付正文；再发「规划：识别为 chat」「复核：确认没有
    create」会连同模型推理卡变成三张一模一样的「已思考」。
    """
    if mode is not None:
        return emits_stage_thoughts(mode)
    if intent == "chat":
        return False
    if command in _DETERMINISTIC_SLASH:
        return False
    return True


def session_harness(session_id: str) -> SessionHarness | None:
    """读取当前会话的进行中回合。"""
    return _HARNESS_BY_SESSION.get(session_id)


def _clear_harness(session_id: str, task: asyncio.Task | None) -> None:
    current = _HARNESS_BY_SESSION.get(session_id)
    if current and (task is None or current.task is task):
        _HARNESS_BY_SESSION.pop(session_id, None)


def abort_running_turn(
    session_id: str,
    *,
    reason: str,
    user_id: str | None = None,
) -> bool:
    """置位同一 CancellationToken，并取消未完成的本地 asyncio.Task。

    返回是否实际发出了本地取消调度。100ms SLO 只覆盖本函数返回前的本地动作，
    不含 MCP 远端往返。无 MCP 客户端时不得声称已向 Server 发取消。
    """
    existing = _HARNESS_BY_SESSION.get(session_id)
    if existing is None or existing.task is None or existing.task.done():
        return False
    if user_id is not None and existing.user_id != user_id:
        return False
    existing.cancel.request(reason)
    existing.stop.set()
    existing.abort.set()
    if existing.task is not None and not existing.task.done():
        existing.task.cancel()
    latency = existing.cancel.dispatch_latency_ms()
    with using_trace(existing.trace):
        if latency is not None:
            agent_trace(f"取消调度 reason={reason} dispatch_latency_ms={latency:.1f}")
        publisher().set_turn_status(existing.trace, status=TurnStatus.CANCELLING, finished=False)
    return True


def _check_abort(abort: asyncio.Event) -> None:
    if abort.is_set():
        raise HarnessAborted()


def _run_with_fresh_db(stop: threading.Event, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """在独立 Session 中执行同步函数，避免与收包循环/取消路径共用同一条连接。"""
    if stop.is_set():
        raise HarnessAborted()
    db = SessionLocal()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


async def _await_thread(stop: threading.Event, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """to_thread 包装：线程用独立库会话；取消后丢弃结果，不往已关闭会话上 commit。"""
    result = await asyncio.to_thread(_run_with_fresh_db, stop, fn, *args, **kwargs)
    if stop.is_set():
        raise HarnessAborted()
    return result


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


def _live_reasoning_sink(
    emit: EmitFn,
    loop: asyncio.AbstractEventLoop,
) -> tuple[list[str], Callable[[str], None]]:
    """规划线程里把推理增量推到思考卡，避免非流式整包空等。"""
    sink: list[str] = []

    def on_reasoning(chunk: str) -> None:
        sink.append(chunk)
        try:
            asyncio.run_coroutine_threadsafe(
                emit("thought", {"text": chunk, "stream": "think"}),
                loop,
            ).result(timeout=STREAM_EMIT_WAIT_S)
        except Exception:
            pass

    return sink, on_reasoning


async def _flush_think_final(emit: EmitFn, sink: list[str]) -> None:
    """规划流结束后落思考快照，供刷新回放。"""
    thought = "".join(sink).strip()[:12000]
    if thought:
        await emit("thought", {"text": thought, "stream": "think_final"})


async def _deliver_sentence(
    db: Session,
    session_id: str,
    emit: EmitFn,
    text: str,
    *,
    task_id: str | None = None,
) -> None:
    """交付句：先 thought 事件，再写入 messages.role=assistant。

    latency_ms：本轮 Harness 墙钟耗时（毫秒），来自 contextvar ``_ROUND_STARTED_AT``。
    ``reply_latency_ms`` 走 thought 终帧实时下发（区别于各阶段耗时的 ``latency_ms``，
    不破坏前端交付帧判定）；同时落库 ``messages.latency_ms`` 供历史回放展示。
    """
    latency_ms = None
    round_started = _ROUND_STARTED_AT.get()
    if round_started is not None:
        latency_ms = max(0, int((datetime.now(UTC) - round_started).total_seconds() * 1000))
    payload: dict[str, Any] = {"text": text}
    if latency_ms is not None:
        payload["reply_latency_ms"] = latency_ms
    trace = current_trace()
    if trace is not None:
        # 仅在最终回复实际发出并即将落库时进入收尾，外层 finally 在提交后写 FINISHED。
        begin_finalizing_delivery(trace=trace)
    await emit("thought", payload, task_id=task_id)
    agent_trace(f"交付助手回复 chars={len(text)} latency={latency_ms or 0}ms")
    trace = current_trace()
    message = Message(
        session_id=session_id,
        role="assistant",
        content=text,
        latency_ms=latency_ms,
        origin_trace_id=trace.trace_id if trace else None,
        origin_span_id=trace.span_id if trace else None,
    )
    db.add(message)
    db.commit()
    # 生产 Turn 必有 trace；测试或旧入口无 trace 时保留既有消息落库行为。
    if trace is not None:
        await append_persisted_conversation_message(db, message, trace=trace)


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
    # 只有 verdict=clarify 的 reasons 才是真正的澄清理由；
    # verdict=pass 时 reasons 是门禁通过语（如「确认没有 create」），
    # 若 plan.delivery=clarify 走到本函数，不得把通过语当澄清句交付给用户。
    if reflect.verdict == "clarify" and reflect.reasons:
        return str(reflect.reasons[0])
    missing = plan.slots.get("missing") or []
    if missing:
        return f"还需要确认：{', '.join(missing)}。可以说具体协议档和数据集，或发送 /benchmark。"
    # 规划自身判 clarify（意图不清）但门禁通过：用规划短句说明，避免答非所问
    if plan.delivery == "clarify" and plan.notes:
        notes = plan.notes.rstrip("。")
        if VOICECLONE_CLARIFY_RE.search(notes) or AUDIO_CLARIFY_RE.search(notes):
            return f"{notes}。"
        return f"{notes}。可以补充评测目标（协议档、数据集），或直接发送 /benchmark。"
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
    stop: threading.Event,
    trace: TraceContext,
    cancel: CancellationToken,
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

    # 未知斜杠（含 /foo 这种正则能解析出命令名的未注册词）须在规划前交付帮助
    if is_unknown_slash(parsed):
        await _deliver_sentence(db, session.id, emit, unknown_command_text())
        return

    parsed_cmd = parsed.command or ""
    if session.title == "新会话" and text.strip() and parsed_cmd not in NO_TITLE_COMMANDS:
        session.title = _title_from_text(text)
        db.commit()

    prefs = load_prefs(db, user.id)
    history = await history_for_plan(db, session, trace=trace)
    compact_summary = getattr(session, "compact_summary", None)
    budget = TurnBudget(cap=MAX_MODEL_CALLS)

    try:
        plan = await _await_thread(
            stop,
            lambda tdb: run_plan(
                tdb,
                text=text,
                parsed=parsed,
                history=history,
                prefs=prefs,
                attachments=attachments,
                budget=budget,
                model_available=True,
                compact_summary=compact_summary,
                cancel=cancel,
                trace=trace,
            ),
        )
    except TurnCancelled as exc:
        raise HarnessAborted() from exc
    _check_abort(abort)
    mode = resolve_turn_mode(text=text, parsed=parsed, plan=plan)
    agent_trace(
        f"TurnMode 调度 mode={mode.value} loop={plan.loop or '-'} "
        f"complexity={plan.complexity or '-'} intent={plan.intent} tools={plan.tools_needed}"
    )
    emit_stage_thoughts = should_emit_stage_thoughts(plan.intent, parsed.command, mode)
    if emit_stage_thoughts:
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
        for pref_note in plan.pref_thoughts:
            await _emit_thought(emit, pref_note, stage="plan")

    slash_fill_first = parsed.command in {"benchmark", "stress", "testcase", "rerun"}
    use_llm_react = uses_react_llm(
        mode, command=parsed.command, slash_fill_first=slash_fill_first
    )

    _check_abort(abort)
    try:
        react = await run_react(
            db,
            plan,
            user_id=user.id,
            emit=emit,
            check_abort=lambda: _check_abort(abort),
            slash_fill_first=slash_fill_first,
            text=text,
            attachments=attachments,
            use_llm=use_llm_react,
            stop=stop,
            history=history,
            compact_summary=compact_summary,
            trace=trace,
            cancel=cancel,
        )
    except TurnCancelled as exc:
        raise HarnessAborted() from exc
    for note in react.pref_stale_notes:
        await _emit_thought(emit, note, stage="react")

    # 补规划：仅 Plan-and-Solve 且仍缺槽时 1 次（HAR-ACT-04）。斜杠缺槽同样允许。
    missing = (plan.slots.get("missing") or []) if plan.intent in {"benchmark", "rag", "testcase"} else []
    if allows_replan(mode) and missing and budget.remaining() > 0 and plan.delivery == "confirm":
        _check_abort(abort)
        await _emit_thought(emit, "补规划：根据工具观察调整槽位", stage="plan")
        loop = asyncio.get_running_loop()
        replan_thought, on_replan_reasoning = _live_reasoning_sink(emit, loop)
        replan_span = trace.child("orchestration.replan")
        try:
            extra = await _await_thread(
                stop,
                lambda tdb: run_replan(
                    tdb,
                    text=text,
                    parsed=parsed,
                    history=history,
                    prefs=prefs,
                    attachments=attachments,
                    budget=budget,
                    plan=plan,
                    observations=list(react.observations),
                    compact_summary=compact_summary,
                    cancel=cancel,
                    trace=replan_span,
                    on_reasoning=on_replan_reasoning,
                ),
            )
        except TurnCancelled as exc:
            raise HarnessAborted() from exc
        await _flush_think_final(emit, replan_thought)
        executed_names = [str(obs.get("name") or "") for obs in react.observations]
        plan, extra_tools = merge_replan(plan, extra, executed_tool_names=executed_names)
        if extra_tools and plan.delivery == "confirm":
            stale_before = len(react.pref_stale_notes)
            try:
                react = await run_react(
                    db,
                    plan,
                    user_id=user.id,
                    emit=emit,
                    check_abort=lambda: _check_abort(abort),
                    slash_fill_first=slash_fill_first,
                    prior=react,
                    extra_tools=extra_tools,
                    text=text,
                    attachments=attachments,
                    use_llm=use_llm_react,
                    stop=stop,
                    history=history,
                    compact_summary=compact_summary,
                    trace=trace,
                    cancel=cancel,
                )
            except TurnCancelled as exc:
                raise HarnessAborted() from exc
            for note in react.pref_stale_notes[stale_before:]:
                await _emit_thought(emit, note, stage="react")

    _check_abort(abort)
    reflect = run_gates(db, session=session, plan=plan, react=react, source="plan")

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

    # 规则优先；仅 Plan-and-Solve 确认卡再做模型核对
    if reflect.verdict == "pass" and allows_model_check(mode):
        _check_abort(abort)
        gate_reasons = list(reflect.reasons)
        reflect = await _await_thread(
            stop,
            lambda tdb, artifact=reflect: maybe_model_check(
                tdb,
                artifact,
                plan=plan,
                text=text,
                budget=budget,
                compact_summary=compact_summary,
                observations=list(react.observations),
            ),
        )
        # /help 等用户目标就是该命令本身；核对改判 clarify 会吞掉确定性交付
        if parsed.command in _DETERMINISTIC_SLASH and reflect.verdict == "clarify":
            reflect.verdict = "pass"
            reflect.reasons = gate_reasons
            reflect.spec = None

    await after_reflect(plan=plan, reflect=reflect)

    if emit_stage_thoughts:
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

    # /compact 在规则 + 核对通过后再执行（压缩调用不计入 4 次硬顶）
    if plan.intent == "compact":
        try:
            session_id = session.id

            def _compact_job(tdb: Session) -> tuple[str, int, int] | None:
                row = tdb.query(AgentSession).filter(AgentSession.id == session_id).first()
                if not row:
                    raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
                return run_compact(tdb, row, stop=stop)

            packed = await _await_thread(stop, _compact_job)
            if packed is None:
                raise HarnessAborted()
            sentence, _old_m, _new_m = packed
        except AppError as exc:
            await emit("error", {"code": exc.code.value, "message": exc.message})
            await _deliver_sentence(db, session.id, emit, "上下文压缩失败，窗口未改动")
            return
        await _deliver_sentence(db, session.id, emit, sentence)
        return

    if parsed.command == "new":
        await _deliver_sentence(db, session.id, emit, "请使用左侧「新建会话」，随后会切换到新的空会话。")
        return
    if parsed.command == "help":
        await _deliver_sentence(db, session.id, emit, enabled_help_text())
        return
    if parsed.command == "status":
        task = (
            db.query(Task)
            .filter(Task.session_id == session.id, Task.status.in_(ACTIVE_STATUSES))
            .first()
        )
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
        await _deliver_sentence(db, session.id, emit, f"当前共 {count} 个协议档。")
        return
    if parsed.command == "datasets":
        count = 0
        for obs in react.observations:
            if obs.get("name") == "dataset.list" and obs.get("ok"):
                count = int((obs.get("data_summary") or {}).get("count") or 0)
        await _deliver_sentence(
            db,
            session.id,
            emit,
            f"当前共 {count} 个数据集。" if count else "还没有数据集，请先到「数据集」页上传。",
        )
        return

    if plan.delivery == "confirm" and reflect.verdict == "pass" and reflect.spec:
        card = dict(reflect.spec)
        # 再读并锁住会话，防止并发回合覆盖尚未处理的确认卡。
        locked_session = (
            db.query(AgentSession)
            .filter(AgentSession.id == session.id, AgentSession.deleted_at.is_(None))
            .with_for_update()
            .first()
        )
        if not locked_session:
            raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
        if locked_session.pending_confirm:
            await emit(
                "error",
                {
                    "code": ErrorCode.CONCURRENCY.value,
                    "message": "当前会话已有待确认任务，请先确认或取消后再发起新任务。",
                },
            )
            return
        locked_session.pending_confirm = card
        locked_session.pending_confirm_author_id = user.id
        db.commit()
        await emit(
            "confirm",
            {
                **card,
                # 元数据不属于 TaskSpec；前端提交 patch 前必须剥离。
                "confirm_author": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                },
            },
        )
        agent_trace(f"生成确认卡 intent={plan.intent} kind={card.get('kind')}")
        return

    if plan.intent == "chat" or plan.delivery == "text":
        image_obs = next(
            (obs for obs in react.observations if obs.get("name") == "image.generate"),
            None,
        )
        if image_obs is not None:
            if image_obs.get("ok"):
                ids = (image_obs.get("data_summary") or {}).get("ids") or []
                file_id = str(ids[0]) if ids else ""
                sentence = "图片已生成。"
                if file_id:
                    sentence = f"图片已生成。file_id={file_id}"
                await _deliver_sentence(db, session.id, emit, sentence)
            else:
                err = (image_obs.get("data_summary") or {}).get("error") or "图像生成失败"
                await _deliver_sentence(db, session.id, emit, err)
            return
        stt_obs = next((obs for obs in react.observations if obs.get("name") == "audio.speech_recognition"), None)
        if stt_obs is not None:
            sentence = "语音识别完成，转写文本已在工具卡中展示。" if stt_obs.get("ok") else ((stt_obs.get("data_summary") or {}).get("error") or "语音识别失败")
            await _deliver_sentence(db, session.id, emit, sentence)
            return
        tts_obs = next((obs for obs in react.observations if obs.get("name") == "audio.speech_synthesis"), None)
        if tts_obs is not None:
            sentence = "语音合成完成，可在工具卡中播放或下载。" if tts_obs.get("ok") else ((tts_obs.get("data_summary") or {}).get("error") or "语音合成失败")
            await _deliver_sentence(db, session.id, emit, sentence)
            return
        clone_obs = next(
            (obs for obs in react.observations if obs.get("name") == "audio.voiceclone"),
            None,
        )
        if clone_obs is not None:
            if clone_obs.get("ok"):
                await _deliver_sentence(
                    db,
                    session.id,
                    emit,
                    "已用参考音频合成配音，可在工具卡中播放或下载。",
                )
            else:
                err = (clone_obs.get("data_summary") or {}).get("error") or "音色合成失败"
                await _deliver_sentence(db, session.id, emit, err)
            return
        if react.reply_text:
            await _deliver_sentence(db, session.id, emit, react.reply_text)
            return
        await _deliver_sentence(db, session.id, emit, "我在，请继续说明你的需求。")
        return

    await _deliver_sentence(db, session.id, emit, plan.notes or "已处理。")


async def _chat_reply(
    _db: Session,
    text: str,
    history: list[dict[str, str]],
    budget: TurnBudget,
    *,
    stop: threading.Event,
    compact_summary: str | None,
    skill_id: str | None,
    emit: EmitFn,
    trace: TraceContext,
    cancel: CancellationToken,
) -> str:
    """闲聊交付句：与规划/重试/补规划/核对共用 4 次硬顶；达顶回退短答，不再调模型。

    正文增量与推理思考链增量经瞬态 WS 帧实时下发；正文由
    ``_deliver_sentence`` 写成 assistant 消息，完整推理链只在本轮成功结束时
    以 ``stream=think_final`` 保存一帧，供历史回放恢复思考卡。取消或异常时
    丢弃半截增量，避免把不完整的模型内部过程写进会话。
    """
    canned = (
        "你好！我是 AI 测试与评估平台的评测智能体。职责是协助你进行大模型质量评测、"
        "PRD 测试用例生成、知识库 RAG 评测与共享压测分析。\n\n"
        "请告诉我你的评测目标（例如：「对比两个模型的表现」或「生成登录模块测试用例」），"
        "我会先为你列出可用资产并组装确认卡，经你确认后再提交执行。"
    )
    if not budget.consume():
        return canned
    user_blob = text if not history else f"最近对话：{history[-6:]}\n用户：{text}"
    system = turn_system(chat_system(), skill_id=skill_id, compact_summary=compact_summary)
    loop = asyncio.get_running_loop()

    def _producer() -> tuple[str, str]:
        from ..llm import stream_agent_model

        cancel.raise_if_cancelled()
        tdb = SessionLocal()
        parts: list[str] = []
        thought_parts: list[str] = []
        frames = 0
        chat_span = trace.child("orchestration.chat")
        try:
            for kind, chunk in stream_agent_model(
                tdb,
                system,
                user_blob,
                trace=chat_span,
                cancel=cancel,
                temperature=0.4,
                max_tokens=2048,
                timeout_s=STREAM_TIMEOUT_S,
            ):
                cancel.raise_if_cancelled()
                if not chunk:
                    continue
                frames += 1
                stream = "think" if kind == "reasoning" else "chunk"
                if kind == "reasoning":
                    thought_parts.append(chunk)
                else:
                    parts.append(chunk)
                try:
                    asyncio.run_coroutine_threadsafe(
                        emit("thought", {"text": chunk, "stream": stream}),
                        loop,
                    ).result(timeout=STREAM_EMIT_WAIT_S)
                except Exception:
                    pass
            text_out = "".join(parts).strip()
            thought_out = "".join(thought_parts).strip()[:12000]
            agent_trace(f"闲聊流式完成 frames={frames} chars={len(text_out)}")
            return text_out, thought_out
        finally:
            tdb.close()

    try:
        result, thought = await asyncio.to_thread(_producer)
        cancel.raise_if_cancelled()
        if stop.is_set():
            raise HarnessAborted()
        if thought:
            # 只保存完整思考快照，不逐 token 写 ws_events，避免事件表膨胀。
            await emit("thought", {"text": thought, "stream": "think_final"})
        return result or canned
    except HarnessAborted:
        raise
    except TurnCancelled as exc:
        raise HarnessAborted() from exc
    except AppError:
        return canned
    except Exception as exc:
        agent_exception("闲聊回复内部异常", exc)
        return canned


async def _harness_entry(
    *,
    session_id: str,
    user_id: str,
    text: str,
    attachments: list[str],
    message_id: str | None,
    emit_factory: Callable[[Session], EmitFn],
    abort: asyncio.Event,
    stop: threading.Event,
    trace: TraceContext,
    cancel: CancellationToken,
) -> None:
    """Harness 任务入口：独立 DB 会话，墙钟默认 180s（含音色克隆），结束后清理 registry。"""
    # 记录回合墙钟起点，供 _deliver_sentence 计算回复耗时 latency_ms 展示给用户。
    _ROUND_STARTED_AT.set(datetime.now(UTC))
    db = SessionLocal()
    task = asyncio.current_task()
    final_status = TurnStatus.FINISHED
    _trace_cm = using_trace(trace)
    _trace_cm.__enter__()
    try:
        session = (
            db.query(AgentSession)
            .filter(AgentSession.id == session_id, AgentSession.deleted_at.is_(None))
            .first()
        )
        user = db.query(User).filter(User.id == user_id).first()
        if not session or not user:
            return
        if message_id:
            # 用户消息先于异步 Turn 落库；在本入口回填真实 trace，避免伪造消息级 trace。
            try:
                message = (
                    db.query(Message)
                    .filter(Message.id == message_id, Message.session_id == session_id)
                    .first()
                )
            except Exception as exc:
                db.rollback()
                agent_trace(f"message trace查询异常 type={type(exc).__name__}")
            else:
                if message is not None:
                    try:
                        message.origin_trace_id = trace.trace_id
                        message.origin_span_id = trace.span_id
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        agent_trace(f"message trace回填异常 type={type(exc).__name__}")
                    else:
                        # 用户消息已先由 WS 持久化；在获得本 Turn trace 后补写组合记忆。
                        # 记忆服务故障必须继续向外层抬升，不能伪装成本轮正常召回。
                        await append_persisted_conversation_message(db, message, trace=trace)
        emit = emit_factory(db)
        publisher().start_turn(trace, session_id=session_id, status=TurnStatus.INIT)

        async def _body() -> None:
            await _run_turn(
                db,
                session=session,
                user=user,
                text=text,
                attachments=attachments,
                emit=emit,
                abort=abort,
                stop=stop,
                trace=trace,
                cancel=cancel,
            )

        await asyncio.wait_for(_body(), timeout=wall_clock_s())
    except TimeoutError:
        cancel.request("deadline")
        stop.set()
        abort.set()
        final_status = TurnStatus.FAILED_STOP
        agent_trace(f"回合墙钟超时 session={session_id[:8]}")
        try:
            emit = emit_factory(db)
            await emit("error", {"code": ErrorCode.TIMEOUT.value, "message": "本轮超时，未出确认卡"})
            await _deliver_sentence(db, session_id, emit, "本轮超时，未出确认卡")
        except Exception as exc:  # noqa: BLE001
            agent_exception("超时交付内部异常", exc)
    except HarnessAborted:
        cancel.request("user_stop")
        stop.set()
        final_status = TurnStatus.CANCELLED
        try:
            emit = emit_factory(db)
            await _deliver_sentence(db, session_id, emit, "已停止生成")
        except Exception as exc:  # noqa: BLE001
            agent_exception("abort 交付内部异常", exc)
    except asyncio.CancelledError:
        cancel.request("user_stop")
        stop.set()
        abort.set()
        final_status = TurnStatus.CANCELLED
        try:
            emit = emit_factory(db)
            await _deliver_sentence(db, session_id, emit, "已停止生成")
        except Exception as exc:  # noqa: BLE001
            agent_exception("cancel 交付内部异常", exc)
        raise
    except AppError as exc:
        final_status = TurnStatus.FAILED_STOP
        agent_trace(f"harness AppError code={exc.code.value}")
        try:
            emit = emit_factory(db)
            await emit("error", {"code": exc.code.value, "message": exc.message})
            await _deliver_sentence(db, session_id, emit, exc.message)
        except Exception:
            pass
    except Exception as exc:
        final_status = TurnStatus.FAILED_STOP
        agent_exception("harness 内部异常", exc)
        try:
            emit = emit_factory(db)
            await emit("error", {"code": ErrorCode.INTERNAL.value, "message": "消息处理失败，请稍后重试"})
        except Exception:
            pass
    finally:
        try:
            publisher().finish_turn(trace, status=final_status)
        except Exception:
            pass
        _trace_cm.__exit__(None, None, None)
        db.close()
        _clear_harness(session_id, task)


async def dispatch_user_message(
    *,
    session_id: str,
    user_id: str,
    text: str,
    attachments: list[str],
    is_session_owner: bool,
    emit_busy: EmitFn,
    emit_factory: Callable[[Session], EmitFn],
    message_id: str | None = None,
) -> None:
    """收包循环调用：共享会话限制 /compact、/stop 的会话级副作用。"""
    parsed = parse_slash(text)
    if parsed.command == "compact" and not is_session_owner:
        await emit_busy(
            "error",
            {"code": ErrorCode.UNAUTHORIZED.value, "message": "仅会话创建者可以压缩共享会话上下文"},
        )
        return

    async with _HARNESS_REGISTRY_LOCK:
        existing = _HARNESS_BY_SESSION.get(session_id)
        running = existing is not None and existing.task is not None and not existing.task.done()

        if running and existing:
            if parsed.command == "stop":
                if existing.user_id != user_id:
                    await emit_busy(
                        "error",
                        {"code": ErrorCode.UNAUTHORIZED.value, "message": "仅本轮发起人可以停止生成"},
                    )
                    return
                abort_running_turn(session_id, reason="user_stop", user_id=user_id)
                return
            await emit_busy("thought", {"text": "正在生成，先 /stop 或等本轮结束"})
            return

        if parsed.command == "stop" and not running:
            await emit_busy("thought", {"text": "当前没有正在生成的内容"})
            return

        trace = TraceContext.for_turn(component="dispatch")
        cancel = CancellationToken(turn_id=trace.turn_id)
        handle = SessionHarness(
            user_id=user_id,
            abort=asyncio.Event(),
            stop=cancel.stop,
            cancel=cancel,
            trace=trace,
        )
        task = asyncio.create_task(
            _harness_entry(
                session_id=session_id,
                user_id=user_id,
                text=text,
                attachments=attachments,
                message_id=message_id,
                emit_factory=emit_factory,
                abort=handle.abort,
                stop=handle.stop,
                trace=trace,
                cancel=cancel,
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
    """确认卡回执。共享会话中仅创建卡的成员可确认、拒绝或提交 patch。"""
    # 确认/拒绝与创建确认卡共用 sessions 行锁，避免两个标签并发消费同一张卡。
    query = db.query(AgentSession).filter(
        AgentSession.id == session.id,
        AgentSession.deleted_at.is_(None),
    )
    if hasattr(query, "with_for_update"):
        query = query.with_for_update()
    locked_session = query.first()
    if locked_session is not None:
        session = locked_session
    base = session.pending_confirm if isinstance(session.pending_confirm, dict) else None

    if base is None:
        await emit("error", {"code": ErrorCode.VALIDATION.value, "message": "没有待确认的评测单，请先发送目标重新生成。"})
        return

    # 旧数据迁移会回填 owner；此处兜底避免历史卡在升级瞬间失去控制人。
    author_id = session.pending_confirm_author_id or session.user_id
    if author_id != user.id:
        await emit(
            "error",
            {"code": ErrorCode.UNAUTHORIZED.value, "message": "仅确认卡发起人可以确认或取消该任务"},
        )
        return

    if not ok:
        session.pending_confirm = None
        session.pending_confirm_author_id = None
        db.commit()
        # 回执本身也进入事件时间线，协作者/历史回放才能区分已取消与仍待确认。
        await emit("confirm_ack", {"ok": False})
        await _deliver_sentence(db, session.id, emit, "已取消本次确认，不会创建任务。需要调整目标可以继续说。")
        return

    merged = deep_merge(deepcopy(base), patch or {})
    if merged.get("kind") == "stress":
        await emit(
            "error",
            {"code": ErrorCode.VALIDATION.value, "message": "压测由质量任务勾选「先评后压」派生，不能单独下单"},
        )
        return
    if merged.get("kind") == "rag":
        await emit(
            "error",
            {"code": ErrorCode.VALIDATION.value, "message": "将在知识库阶段启用"},
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
        # 与已验证的确认卡作者保持同一任务归属，不能被协作者劫持。
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
    session.pending_confirm_author_id = None
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

    # 先记录确认结果，再记录 task.create 工具事件；前端可在协作者连接上即时盖章。
    await emit("confirm_ack", {"ok": True, "task_id": task.id}, task_id=task.id)
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
    # 与 REST cancel 同样先锁定任务行，避免读到 Worker 即将完成前的陈旧 running 状态。
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if not task:
        await emit("error", {"code": ErrorCode.NOT_FOUND.value, "message": "任务不存在"})
        return
    if task.created_by != user.id:
        await emit("error", {"code": ErrorCode.UNAUTHORIZED.value, "message": "没有权限做这件事"}, task_id=task.id)
        return
    if task.session_id and task.session_id != session.id:
        await emit(
            "error",
            {"code": ErrorCode.VALIDATION.value, "message": "只能取消当前会话中的任务"},
            task_id=task.id,
        )
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
        TaskEvent(
            task_id=task.id,
            event="cancelled",
            message="任务已取消",
            payload={"status": "cancelled"},
        )
    )
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
    # _emit 会提交 ws_events；先提交取消事务，避免事件落库提前释放任务行锁。
    await emit("tool_call", {"name": "task.cancel", "arguments": {"task_id": task.id}}, task_id=task.id)
    await emit(
        "tool_result",
        {"name": "task.cancel", "ok": True, "data": {"task_id": task.id, "status": "cancelled"}, "latency_ms": 0},
        task_id=task.id,
    )
    await _deliver_sentence(
        db,
        session.id,
        emit,
        "已收到取消请求，任务状态已更新为 cancelled。",
        task_id=task.id,
    )
