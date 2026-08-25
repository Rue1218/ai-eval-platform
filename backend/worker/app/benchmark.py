"""Benchmark 执行器（使用 LangGraph 状态图工作流编排评测流水线）。

执行流程（PRD 5.2.2 / 后端开发计划 §12.4）：
1. 载入任务快照 → 数据集可用行（待补全行不进分母）→ 协议档；
2. 构建并调用 LangGraph 评测图，逐 profile 分批并发调用被测（批大小 = min(run.concurrency, max_inflight_model_calls)）；
3. 每样本落 `eval_items`（唯一键 task+profile+row_no，Worker 重启按行号续跑）；
4. 逐调用累加 `usage_ledger`，费用超 `default_max_usd` 即停 → failed + BUDGET_EXCEEDED；
5. 取消为协作式：每批完成后检查任务状态，当前样本（批）结束后停止；
6. 全部完成写报告 metrics（scores / sample_items）并置 succeeded。

失败样本记 `eval_items.error` 不中断整次评测；报告由 Worker 写入，
浏览器仅做只读回放，不在前端拼接成功报告。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from .db import SessionLocal
from .eval_graph import BenchmarkEvalPipeline, BenchmarkGraphState
from .events import push_ws
from .judge import build_judge_call_kwargs, judge_single_sample
from .models import (
    Dataset,
    DatasetRow,
    EvalItem,
    ProtocolProfile,
    Report,
    Setting,
    Task,
    TaskEvent,
    UsageLedger,
)
from .profile_env import profile_connection
from .sampling import clamp_sample_size
from .scoring import DEFAULT_METRIC
from .stress_spawn import maybe_spawn_stress
from .task_state import claim_running_task_for_terminal_write

logger = logging.getLogger("worker.benchmark")

# ─── 平台默认值（与 api 侧 admin.DEFAULT_SETTINGS 保持一致） ───
DEFAULT_MAX_INFLIGHT = 8
DEFAULT_MAX_USD = 5.0
DEFAULT_PRICE_PER_1K = 0.002
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT_S = 30.0

# 上游原始响应落库上限（PRD 5.2.2：raw ≤ 32KB）
RAW_MAX_BYTES = 32 * 1024

# 终态集合（与 main.py TERMINAL 一致）
_TERMINAL = {"succeeded", "failed", "cancelled"}


def _now() -> datetime:
    """统一使用 UTC 时间戳。"""
    return datetime.now(UTC)


def _setting_value(db: Session, key: str):
    """读取平台配置值；未配置时返回 None。"""
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else None


def _price_per_1k(db: Session) -> float:
    """读取单价（USD / 1k tokens）；缺失或非法时回退默认 0.002。"""
    stress = _setting_value(db, "stress")
    value = stress.get("price_per_1k_tokens") if isinstance(stress, dict) else None
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    return DEFAULT_PRICE_PER_1K


def _max_usd(db: Session) -> float:
    """读取单任务预算上限（USD）；缺失或非法时回退默认 5。"""
    value = _setting_value(db, "default_max_usd")
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    return DEFAULT_MAX_USD


def _max_inflight(db: Session) -> int:
    """读取平台在途调用上限；缺失或非法时回退默认 8。"""
    value = _setting_value(db, "max_inflight_model_calls")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return DEFAULT_MAX_INFLIGHT


def _truncate_raw(raw: dict) -> dict:
    """上游原始响应截断到 32KB；超长降级为文本前缀，保证 JSONB 始终合法。"""
    try:
        text = json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"truncated": True, "text": str(raw)[:RAW_MAX_BYTES]}
    if len(text.encode("utf-8")) <= RAW_MAX_BYTES:
        return raw
    return {"truncated": True, "text": text[:RAW_MAX_BYTES]}


def _load_usage(db: Session, task_id: str) -> dict[str, dict]:
    """从台账恢复累计用量（Worker 重启续跑时预算口径不重置）。"""
    totals: dict[str, dict] = {}
    for row in db.query(UsageLedger).filter(UsageLedger.task_id == task_id).all():
        totals[row.profile_id] = {
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "total_tokens": row.total_tokens or 0,
            "est_cost_usd": row.est_cost_usd or 0.0,
        }
    return totals


def _is_cancelled(db: Session, task_id: str) -> bool:
    """协作式取消检查：重新查询任务当前状态（取消由 cancel API 置位）。"""
    db.expire_all()
    row = db.query(Task.status).filter(Task.id == task_id).first()
    return bool(row) and row[0] in {"cancelled", "failed"}


def _progress(db: Session, task_id: str, done: int, total: int, message: str) -> None:
    """更新任务进度字段并推送 WS progress 事件（契约字段：percent/done/total/message）。

    必须按 task_id 在本 Session 内重新加载 ORM，禁止把其它 Session 的 Task
    实例传进来（跨 Session 赋值不会进入脏检查，tasks.progress 会停在初值）。
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return
    percent = round(done * 100 / total) if total else 100
    task.progress = {"percent": percent, "done": done, "total": total, "message": message}
    db.add(
        TaskEvent(
            task_id=task.id,
            event="progress",
            message=f"{message}（{done}/{total}）",
            payload={"percent": percent, "done": done, "total": total},
        )
    )
    db.commit()
    push_ws(
        task.session_id,
        "progress",
        {"percent": percent, "done": done, "total": total, "message": message},
        task_id=task.id,
    )


def _fail(db: Session, task: Task, code: str, message: str) -> None:
    """任务失败收尾：落终态、写错误时间线并推送 WS error 事件。"""
    task_id = task.id
    task = claim_running_task_for_terminal_write(db, task_id)
    if not task:
        logger.info("benchmark task %s skipped failure because it is no longer running", task_id)
        return
    task.status = "failed"
    task.finished_at = _now()
    task.result = {**(task.result or {}), "error_code": code, "error_message": message}
    db.add(TaskEvent(task_id=task.id, event="error", level="error", message=message, payload={"code": code}))
    db.commit()
    push_ws(task.session_id, "error", {"code": code, "message": message}, task_id=task.id)
    logger.warning("benchmark task %s failed (%s): %s", task.id, code, message)


def _avg(values: list) -> float | None:
    """求均值（保留 4 位小数）；空列表返回 None。"""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _persist_usage(db: Session, task_id: str, usage_totals: dict[str, dict]) -> None:
    """按 (task_id, profile_id) upsert UsageLedger。

    既有缺口：eval_graph 仅在进程内累加 usage_totals，从未落库，导致报告
    usage/est_cost_usd 恒为 0。此 helper 将目标与裁判 usage 一并写回台账，
    纯增量，不改打分语义。
    """
    for profile_id, totals in usage_totals.items():
        row = (
            db.query(UsageLedger)
            .filter(UsageLedger.task_id == task_id, UsageLedger.profile_id == profile_id)
            .first()
        )
        values = {
            "prompt_tokens": int(totals.get("prompt_tokens") or 0),
            "completion_tokens": int(totals.get("completion_tokens") or 0),
            "total_tokens": int(totals.get("total_tokens") or 0),
            "est_cost_usd": float(totals.get("est_cost_usd") or 0.0),
        }
        if row:
            row.prompt_tokens = values["prompt_tokens"]
            row.completion_tokens = values["completion_tokens"]
            row.total_tokens = values["total_tokens"]
            row.est_cost_usd = values["est_cost_usd"]
        else:
            db.add(
                UsageLedger(task_id=task_id, profile_id=profile_id, **values)
            )
    db.commit()


def _run_judge(
    db: Session,
    task: Task,
    judge_profile: ProtocolProfile,
    run_params: dict,
    batch_size: int,
    max_usd: float,
    price: float,
    usage_totals: dict[str, dict],
) -> dict:
    """对全部目标成功样本执行 LLM 裁判打分（pipeline 完成后、写报告前）。

    1) 查询本任务目标调用成功（无 error 且输出非空）的样本；
    2) 按 batch_size 分批并发调裁判协议档，逐样本回写 judge_score/judge_reason；
    3) judge usage 累加进 usage_totals（计入预算与费用口径，与目标阶段一致）；
    4) 每批后检查协作式取消与预算熔断。
    """
    task_id = task.id
    samples = (
        db.query(EvalItem)
        .filter(
            EvalItem.task_id == task_id,
            EvalItem.error.is_(None),
            EvalItem.output != "",
        )
        .order_by(EvalItem.row_no.asc())
        .all()
    )
    if not samples:
        return {"judged": 0, "failed": 0}

    db.add(
        TaskEvent(
            task_id=task_id,
            event="log",
            message=f"开始 LLM 裁判打分（{len(samples)} 条样本）",
            payload={"profile_id": judge_profile.id, "judged": 0, "total": len(samples)},
        )
    )

    base_url, model, api_key = profile_connection(judge_profile)
    if not api_key:
        logger.warning(
            "benchmark task %s judge profile %s missing API key; judge skipped",
            task_id,
            judge_profile.id,
        )
        return {"judged": 0, "failed": len(samples), "error": "VALIDATION: 裁判协议档未配置 API Key"}

    judge_kwargs = build_judge_call_kwargs(
        protocol=judge_profile.protocol,
        base_url=base_url,
        model=model,
        api_key=api_key,
        anthropic_version=judge_profile.anthropic_version,
        timeout_s=float(run_params.get("timeout_s") or 30.0),
    )
    total = len(samples)
    done = 0
    judged = 0
    failed = 0

    for start in range(0, total, batch_size):
        batch = samples[start : start + batch_size]
        items_data = [
            {
                "question": s.question,
                "reference": s.reference,
                "context": s.context,
                "output": s.output,
            }
            for s in batch
        ]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            results = list(
                pool.map(
                    lambda item_data: judge_single_sample(
                        judge_kwargs, item_data, _truncate_raw
                    ),
                    items_data,
                )
            )
        for sample, result in zip(batch, results):
            done += 1
            if result.get("ok"):
                sample.judge_score = result.get("judge_score")
                sample.judge_reason = result.get("judge_reason")
                judged += 1
            else:
                failed += 1
            usage = result.get("usage")
            if usage:
                totals = usage_totals.setdefault(
                    judge_profile.id,
                    {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "est_cost_usd": 0.0,
                    },
                )
                totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                totals["total_tokens"] += int(usage.get("total_tokens") or 0)
                totals["est_cost_usd"] = totals["total_tokens"] / 1000 * price
        db.commit()
        cost_usd = sum(t["est_cost_usd"] for t in usage_totals.values())
        _progress(db, task_id, done, total, "裁判打分中")

        if _is_cancelled(db, task_id):
            logger.info("benchmark task %s cancelled during judge (judged=%s)", task_id, judged)
            return {"judged": judged, "failed": failed, "cancelled": True}
        if cost_usd > max_usd:
            return {
                "judged": judged,
                "failed": failed,
                "budget_exceeded": True,
                "message": f"裁判阶段费用估算 {cost_usd:.2f} USD 超过上限 {max_usd:.2f} USD，任务已停止",
            }
    return {"judged": judged, "failed": failed}


def _finish(db: Session, task: Task, dataset: Dataset, metric: str, total: int) -> bool:
    """汇总各 profile 指标并安全置 succeeded；已取消时不写报告。"""
    task_id = task.id
    # 最后一批完成与取消请求并发时，以数据库中先取得的终态写锁为准。
    task = claim_running_task_for_terminal_write(db, task_id)
    if not task:
        logger.info("benchmark task %s skipped finish because it is no longer running", task_id)
        return False
    config = task.config or {}
    profile_ids = config.get("profile_ids") or []
    profiles = db.query(ProtocolProfile).filter(ProtocolProfile.id.in_(profile_ids)).all()
    profile_order = {pid: idx for idx, pid in enumerate(profile_ids)}

    scores: list[dict] = []
    sample_items: list[dict] = []
    for profile in sorted(profiles, key=lambda p: profile_order.get(p.id, 0)):
        _profile_base_url, profile_model, _profile_api_key = profile_connection(profile)
        items = (
            db.query(EvalItem)
            .filter(EvalItem.task_id == task.id, EvalItem.profile_id == profile.id)
            .order_by(EvalItem.row_no.asc())
            .all()
        )
        ok_items = [item for item in items if not item.error]
        ledger = (
            db.query(UsageLedger)
            .filter(UsageLedger.task_id == task.id, UsageLedger.profile_id == profile.id)
            .first()
        )
        scores.append(
            {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "model": profile_model,
                "metric": metric,
                # 主指标均值：失败样本不进分母（PRD 5.2.2）
                "score": _avg([item.score for item in ok_items]),
                "exact": _avg([item.exact for item in ok_items]),
                "rouge_l": _avg([item.rouge_l for item in ok_items]),
                # LLM 裁判均值：仅对成功打分的样本求均值，未启用/未判样本为 None
                "judge": _avg([item.judge_score for item in ok_items]),
                "fail_rate": (
                    round((len(items) - len(ok_items)) / len(items), 4) if items else None
                ),
                "latency_ms_avg": _avg([item.latency_ms for item in ok_items]),
                "sample_total": len(items),
                "sample_failed": len(items) - len(ok_items),
                "usage": {
                    "prompt_tokens": ledger.prompt_tokens if ledger else 0,
                    "completion_tokens": ledger.completion_tokens if ledger else 0,
                    "total_tokens": ledger.total_tokens if ledger else 0,
                },
                "est_cost_usd": round(ledger.est_cost_usd, 4) if ledger else 0.0,
            }
        )
        sample_items.extend(
            {
                "row_no": item.row_no,
                "profile_id": profile.id,
                "score": item.score,
                "latency_ms": item.latency_ms,
                "error": item.error,
            }
            for item in items
        )

    # ─── LLM 裁判信息块（仅 use_judge 任务存在） ───
    judge_block: dict | None = None
    judge_profile_id = (config.get("run") or {}).get("judge_profile_id")
    if judge_profile_id:
        judge_profile_row = (
            db.query(ProtocolProfile).filter(ProtocolProfile.id == judge_profile_id).first()
        )
        _judge_base, judge_model, _judge_key = (
            profile_connection(judge_profile_row) if judge_profile_row else (None, None, None)
        )
        judge_ledger = (
            db.query(UsageLedger)
            .filter(UsageLedger.task_id == task.id, UsageLedger.profile_id == judge_profile_id)
            .first()
        )
        all_items = db.query(EvalItem).filter(EvalItem.task_id == task.id).all()
        judged_count = len([item for item in all_items if item.judge_score is not None])
        judge_block = {
            "profile_id": judge_profile_id,
            "profile_name": judge_profile_row.name if judge_profile_row else None,
            "model": judge_model,
            "usage": {
                "prompt_tokens": judge_ledger.prompt_tokens if judge_ledger else 0,
                "completion_tokens": judge_ledger.completion_tokens if judge_ledger else 0,
                "total_tokens": judge_ledger.total_tokens if judge_ledger else 0,
            },
            "est_cost_usd": round(judge_ledger.est_cost_usd, 4) if judge_ledger else 0.0,
            "judged_count": judged_count,
            "failed_count": max(0, len(all_items) - judged_count),
        }

    report = Report(
        task_id=task.id,
        kind="benchmark",
        metrics={
            "metric": metric,
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "dataset_version": dataset.version,
            # 分母口径在报告内可见（前端页脚同文案）
            "denominator_note": "待补全行（question/reference 缺失）不进评分分母；失败样本不计入主指标均值；裁判分仅对调用成功且成功打分的样本求均值",
            "scores": scores,
            # 报告内只放前 50 条摘要，完整逐题比对走 /api/reports/{id}/samples
            "sample_items": sample_items[:50],
            "sample_total": total,
        },
    )
    if judge_block:
        report.metrics["judge"] = judge_block  # type: ignore[index]
    db.add(report)
    db.flush()
    task.status = "succeeded"
    task.finished_at = _now()
    task.report_id = report.id
    task.result = {"metric": metric, "profile_count": len(scores), "sample_total": total}
    task.progress = {"percent": 100, "done": total, "total": total, "message": "任务已完成"}
    db.add(TaskEvent(task_id=task.id, event="finish", payload={"status": "succeeded"}))
    db.commit()

    push_ws(
        task.session_id,
        "progress",
        {"percent": 100, "done": total, "total": total, "message": "任务已完成"},
        task_id=task.id,
    )
    push_ws(task.session_id, "report", {"report_id": report.id}, task_id=task.id)
    logger.info("benchmark task %s succeeded (report=%s)", task.id, report.id)
    maybe_spawn_stress(db, task)
    return True


def run_benchmark(task_id: str) -> None:
    """Benchmark 任务执行入口：通过 LangGraph 工作流编排执行。"""
    db = SessionLocal()
    task: Task | None = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error("benchmark task %s not found, skip execution", task_id)
            return
        config = task.config or {}
        run = config.get("run") or {}

        # ─── 载入数据集与可用行（待补全行不进分母） ───
        dataset = db.query(Dataset).filter(Dataset.id == config.get("dataset_id")).first()
        if not dataset:
            _fail(db, task, "VALIDATION", "关联数据集不存在，任务无法执行")
            return
        rows = (
            db.query(DatasetRow)
            .filter(DatasetRow.dataset_id == dataset.id, DatasetRow.pending_complete.is_(False))
            .order_by(DatasetRow.row_no.asc())
            .all()
        )
        sample_size = clamp_sample_size(run.get("sample_size"), len(rows))
        rows = rows[:sample_size]
        if not rows:
            _fail(db, task, "VALIDATION", "数据集没有可评测的有效行（待补全行不计入分母）")
            return

        # ─── 载入协议档（1–5 个） ───
        profile_ids = config.get("profile_ids") or []
        profiles = db.query(ProtocolProfile).filter(ProtocolProfile.id.in_(profile_ids)).all()
        # 先去重再比对:重复 id 会被误判为「档位不存在」
        missing = set(profile_ids) - {profile.id for profile in profiles}
        if missing:
            _fail(db, task, "VALIDATION", f"有 {len(missing)} 个协议档不存在或已删除")
            return

        # ─── 运行参数与平台闸门 ───
        metric = dataset.metric or DEFAULT_METRIC
        max_usd = _max_usd(db)
        price = _price_per_1k(db)
        concurrency = run.get("concurrency")
        concurrency = concurrency if isinstance(concurrency, int) and concurrency >= 1 else DEFAULT_CONCURRENCY
        batch_size = max(1, min(concurrency, _max_inflight(db)))
        timeout_s = run.get("timeout_s")
        timeout_s = float(timeout_s) if isinstance(timeout_s, int | float) else DEFAULT_TIMEOUT_S
        retry = run.get("retry")
        retry = retry if isinstance(retry, int) and retry >= 0 else 0
        temperature = run.get("temperature")
        temperature = float(temperature) if isinstance(temperature, int | float) else 0.2
        max_tokens = run.get("max_tokens")
        max_tokens = int(max_tokens) if isinstance(max_tokens, int) and max_tokens >= 1 else 1024
        system_prompt = run.get("system_prompt") or None

        total = len(rows) * len(profiles)
        done = db.query(EvalItem).filter(EvalItem.task_id == task.id).count()
        if done >= total:
            # 极端续跑场景：样本已全部落库，直接汇总出报告
            _finish(db, task, dataset, metric, total)
            return
        _progress(db, task.id, done, total, "执行中")

        usage_totals = _load_usage(db, task.id)

        # 整理传递给 LangGraph 的纯字典结构数据
        rows_data = [
            {
                "row_no": r.row_no,
                "question": r.question,
                "reference": r.reference,
                "context": r.context,
            }
            for r in rows
        ]
        profiles_data = []
        for p in profiles:
            base_url, model, api_key = profile_connection(p)
            profiles_data.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "protocol": p.protocol,
                    "base_url": base_url,
                    "model": model,
                    "api_key": api_key,
                    "anthropic_version": p.anthropic_version,
                }
            )

        pipeline = BenchmarkEvalPipeline(
            db_factory=SessionLocal,
            push_progress_fn=lambda tid, d, tot, msg: _progress(db, tid, d, tot, msg),
            truncate_raw_fn=_truncate_raw,
            is_cancelled_fn=_is_cancelled,
        )

        initial_state: BenchmarkGraphState = {
            "task_id": task.id,
            "dataset_id": dataset.id,
            "metric": metric,
            "rows_data": rows_data,
            "profiles_data": profiles_data,
            "run_params": {
                "retry": retry,
                "timeout_s": timeout_s,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "system_prompt": system_prompt,
            },
            "max_usd": max_usd,
            "price_per_1k": price,
            "batch_size": batch_size,
            "total_samples": total,
            "done_samples": done,
            "usage_totals": usage_totals,
            "is_cancelled": False,
            "is_budget_exceeded": False,
            "completed": False,
        }

        # 调用 LangGraph 执行评测工作流
        final_state = pipeline.run(initial_state)

        # 检查取消或预算熔断等终态分支
        if final_state.get("is_cancelled"):
            logger.info(
                "benchmark task %s cancelled mid-run (done=%s/%s)",
                task_id,
                final_state.get("done_samples", done),
                total,
            )
            return

        if final_state.get("is_budget_exceeded") or final_state.get("error_code") == "BUDGET_EXCEEDED":
            _fail(
                db,
                task,
                "BUDGET_EXCEEDED",
                final_state.get("error_message") or "费用超限，任务已停止",
            )
            return

        if final_state.get("error_code"):
            _fail(
                db,
                task,
                final_state["error_code"],
                final_state.get("error_message") or "评测执行异常",
            )
            return

        # 目标阶段用量写回台账（修复 UsageLedger 从未落库的缺口）
        _persist_usage(db, task.id, final_state.get("usage_totals") or usage_totals)

        # ─── LLM 裁判阶段（可选）：pipeline 正常完成后、写报告前 ───
        run = config.get("run") or {}
        if run.get("use_judge") and run.get("judge_profile_id"):
            judge_profile = (
                db.query(ProtocolProfile)
                .filter(ProtocolProfile.id == run["judge_profile_id"])
                .first()
            )
            if not judge_profile:
                _fail(db, task, "VALIDATION", "裁判协议档不存在或已删除")
                return
            judge_result = _run_judge(
                db,
                task,
                judge_profile,
                initial_state["run_params"],
                batch_size,
                max_usd,
                price,
                usage_totals,
            )
            if judge_result.get("cancelled"):
                return  # 取消不写报告，与目标阶段一致
            if judge_result.get("error"):
                _fail(
                    db,
                    task,
                    "VALIDATION",
                    str(judge_result.get("error") or "裁判失败").removeprefix("VALIDATION: "),
                )
                return
            if judge_result.get("budget_exceeded"):
                _fail(
                    db,
                    task,
                    "BUDGET_EXCEEDED",
                    judge_result.get("message") or "裁判阶段费用超限，任务已停止",
                )
                return
            _persist_usage(db, task.id, usage_totals)

        _finish(db, task, dataset, metric, total)
    except Exception as exc:
        db.rollback()
        # 详细堆栈只进服务端日志;给浏览器/事件流的失败原因仅透出异常类名,
        # 便于定位(如 IntegrityError/ValueError)且不泄漏 SQL、路径或凭据
        logger.exception("benchmark task %s execution error", task_id)
        if task is not None:
            _fail(db, task, "INTERNAL", f"执行失败({type(exc).__name__}),详情见服务端日志")
    finally:
        db.close()
