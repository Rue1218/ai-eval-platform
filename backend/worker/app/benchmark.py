"""Benchmark 真实执行器（M2 W6–W7：三协议真调用 + 规则评分 + 预算熔断 + 断点续跑）。

执行流程（PRD 5.2.2 / 后端开发计划 §12.4）：
1. 载入任务快照 → 数据集可用行（待补全行不进分母）→ 协议档；
2. 逐 profile 分批并发调用被测（批大小 = min(run.concurrency, max_inflight_model_calls)）；
3. 每样本落 ``eval_items``（唯一键 task+profile+row_no，Worker 重启按行号续跑）；
4. 逐调用累加 ``usage_ledger``，费用超 ``default_max_usd`` 即停 → failed + BUDGET_EXCEEDED；
5. 取消为协作式：每批完成后检查任务状态，当前样本（批）结束后停止；
6. 全部完成写报告 metrics（scores / sample_items）并置 succeeded。

失败样本记 ``eval_items.error`` 不中断整次评测；报告由 Worker 写入，
浏览器仅做只读回放，不在前端拼接成功报告。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .crypto import decrypt_secret
from .db import SessionLocal
from .events import push_ws
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
from .protocol import ProtocolCallError, call_protocol
from .scoring import DEFAULT_METRIC, score_answer, score_exact, score_rouge_l
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
    return datetime.now(timezone.utc)


def _setting_value(db: Session, key: str):
    """读取平台配置值；未配置时返回 None。"""
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else None


def _price_per_1k(db: Session) -> float:
    """读取单价（USD / 1k tokens）；缺失或非法时回退默认 0.002。"""
    stress = _setting_value(db, "stress")
    value = stress.get("price_per_1k_tokens") if isinstance(stress, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return DEFAULT_PRICE_PER_1K


def _max_usd(db: Session) -> float:
    """读取单任务预算上限（USD）；缺失或非法时回退默认 5。"""
    value = _setting_value(db, "default_max_usd")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return DEFAULT_MAX_USD


def _max_inflight(db: Session) -> int:
    """读取平台在途调用上限；缺失或非法时回退默认 8。"""
    value = _setting_value(db, "max_inflight_model_calls")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return DEFAULT_MAX_INFLIGHT


def _build_user_message(row: DatasetRow) -> str:
    """组装单样本用户消息：question 为正文，context 作为背景前置。"""
    if row.context and row.context.strip():
        return f"背景信息:\n{row.context.strip()}\n\n问题:{row.question}"
    return row.question or ""


def _truncate_raw(raw: dict) -> dict:
    """上游原始响应截断到 32KB；超长降级为文本前缀，保证 JSONB 始终合法。"""
    try:
        text = json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"truncated": True, "text": str(raw)[:RAW_MAX_BYTES]}
    if len(text.encode("utf-8")) <= RAW_MAX_BYTES:
        return raw
    return {"truncated": True, "text": text[:RAW_MAX_BYTES]}


def _eval_one(call_kwargs: dict, row: DatasetRow, retry: int, metric: str) -> dict:
    """调用被测模型并按主指标评分；重试耗尽后返回错误样本（不中断整次评测）。"""
    messages = [{"role": "user", "content": _build_user_message(row)}]
    reference = row.reference or ""
    last_error = ""
    for _ in range(max(1, retry + 1)):
        try:
            result = call_protocol(messages=messages, **call_kwargs)
        except ProtocolCallError as exc:
            last_error = f"{exc.code}: {exc.message}"
            continue
        output = result.text or ""
        return {
            "ok": True,
            "output": output,
            "score": score_answer(metric, output, reference),
            "exact": score_exact(output, reference),
            "rouge_l": score_rouge_l(output, reference),
            "latency_ms": result.latency_ms,
            "usage": result.usage,
            "raw": _truncate_raw(result.raw),
        }
    return {"ok": False, "error": last_error or "UPSTREAM: 调用失败"}


def _save_item(db: Session, task: Task, profile_id: str, row: DatasetRow, result: dict) -> None:
    """落一行样本结果；question/reference/context 按执行时点快照保存。"""
    db.add(
        EvalItem(
            task_id=task.id,
            profile_id=profile_id,
            row_no=row.row_no,
            question=row.question or "",
            reference=row.reference or "",
            context=row.context,
            output=result.get("output") or "",
            score=result.get("score"),
            exact=result.get("exact"),
            rouge_l=result.get("rouge_l"),
            latency_ms=result.get("latency_ms"),
            error=result.get("error"),
            raw=result.get("raw"),
            usage=result.get("usage"),
        )
    )


def _upsert_ledger(db: Session, task_id: str, profile_id: str, totals: dict) -> None:
    """按「任务 × 协议档」累加 upsert 用量台账行。"""
    row = (
        db.query(UsageLedger)
        .filter(UsageLedger.task_id == task_id, UsageLedger.profile_id == profile_id)
        .first()
    )
    if row is None:
        db.add(
            UsageLedger(
                task_id=task_id,
                profile_id=profile_id,
                prompt_tokens=totals["prompt_tokens"],
                completion_tokens=totals["completion_tokens"],
                total_tokens=totals["total_tokens"],
                est_cost_usd=totals["est_cost_usd"],
            )
        )
    else:
        row.prompt_tokens = totals["prompt_tokens"]
        row.completion_tokens = totals["completion_tokens"]
        row.total_tokens = totals["total_tokens"]
        row.est_cost_usd = totals["est_cost_usd"]


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


def _progress(db: Session, task: Task, done: int, total: int, message: str) -> None:
    """更新任务进度字段并推送 WS progress 事件（契约字段：percent/done/total/message）。"""
    percent = round(done * 100 / total) if total else 100
    task.progress = {"percent": percent, "done": done, "total": total, "message": message}
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
                "model": profile.model,
                "metric": metric,
                # 主指标均值：失败样本不进分母（PRD 5.2.2）
                "score": _avg([item.score for item in ok_items]),
                "exact": _avg([item.exact for item in ok_items]),
                "rouge_l": _avg([item.rouge_l for item in ok_items]),
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

    report = Report(
        task_id=task.id,
        kind="benchmark",
        metrics={
            "metric": metric,
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "dataset_version": dataset.version,
            # 分母口径在报告内可见（前端页脚同文案）
            "denominator_note": "待补全行（question/reference 缺失）不进评分分母；失败样本不计入主指标均值",
            "scores": scores,
            # 报告内只放前 50 条摘要，完整逐题比对走 /api/reports/{id}/samples
            "sample_items": sample_items[:50],
            "sample_total": total,
        },
    )
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
    return True


def run_benchmark(task_id: str) -> None:
    """Benchmark 任务真实执行入口：由 main._run_task 在领取任务后调用。"""
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
        sample_size = run.get("sample_size")
        if isinstance(sample_size, int) and not isinstance(sample_size, bool) and sample_size > 0:
            # 确定性抽样：按行号升序取前 N 条，续跑时抽样口径不漂移
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
        timeout_s = float(timeout_s) if isinstance(timeout_s, (int, float)) else DEFAULT_TIMEOUT_S
        retry = run.get("retry")
        retry = retry if isinstance(retry, int) and retry >= 0 else 0
        temperature = run.get("temperature")
        temperature = float(temperature) if isinstance(temperature, (int, float)) else 0.2
        max_tokens = run.get("max_tokens")
        max_tokens = int(max_tokens) if isinstance(max_tokens, int) and max_tokens >= 1 else 1024
        system_prompt = run.get("system_prompt") or None

        total = len(rows) * len(profiles)
        done = db.query(EvalItem).filter(EvalItem.task_id == task.id).count()
        if done >= total:
            # 极端续跑场景：样本已全部落库，直接汇总出报告
            _finish(db, task, dataset, metric, total)
            return
        _progress(db, task, done, total, "执行中")

        # ─── 逐 profile 分批执行 ───
        usage_totals = _load_usage(db, task.id)
        cost_usd = sum(t["est_cost_usd"] for t in usage_totals.values())
        for profile in profiles:
            # 断点续跑：跳过该 profile 已落库的行号
            finished_nos = {
                row_no
                for (row_no,) in db.query(EvalItem.row_no).filter(
                    EvalItem.task_id == task.id, EvalItem.profile_id == profile.id
                ).all()
            }
            pending = [row for row in rows if row.row_no not in finished_nos]
            if not pending:
                continue

            if not profile.encrypted_key:
                # 无 Key 档位：全部样本记 VALIDATION 错误，不中断其它档评测
                for row in pending:
                    _save_item(
                        db, task, profile.id, row, {"ok": False, "error": "VALIDATION: 协议档未配置 API Key"}
                    )
                    done += 1
                db.commit()
                _progress(db, task, done, total, "执行中")
                continue

            call_kwargs = dict(
                protocol=profile.protocol,
                base_url=profile.base_url,
                model=profile.model,
                api_key=decrypt_secret(profile.encrypted_key),
                anthropic_version=profile.anthropic_version,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            )
            for start in range(0, len(pending), batch_size):
                batch = pending[start : start + batch_size]
                # 批内按并发上限并行调用被测（批大小 = min(run.concurrency, max_inflight)）；
                # 单线程池随批创建随批回收，取消/预算检查发生在批与批之间
                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    results = list(
                        pool.map(lambda row: _eval_one(call_kwargs, row, retry, metric), batch)
                    )
                for row, result in zip(batch, results):
                    # 失败样本记 error 落库，不中断整次评测（PRD 5.2.2）
                    _save_item(db, task, profile.id, row, result)
                    done += 1
                    usage = result.get("usage")
                    if usage:
                        totals = usage_totals.setdefault(
                            profile.id,
                            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "est_cost_usd": 0.0},
                        )
                        totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                        totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                        totals["total_tokens"] += int(usage.get("total_tokens") or 0)
                        totals["est_cost_usd"] = totals["total_tokens"] / 1000 * price
                        _upsert_ledger(db, task.id, profile.id, totals)
                db.commit()
                cost_usd = sum(t["est_cost_usd"] for t in usage_totals.values())
                _progress(db, task, done, total, "执行中")

                # 协作式取消：当前批结束后检查（PRD 2.1：评测=当前样本结束后停）
                if _is_cancelled(db, task_id):
                    logger.info("benchmark task %s cancelled mid-run (done=%s/%s)", task_id, done, total)
                    return
                # 预算熔断：费用超限立即停止后续派发（BUDGET_EXCEEDED）
                if cost_usd > max_usd:
                    _fail(
                        db,
                        task,
                        "BUDGET_EXCEEDED",
                        f"费用估算 {cost_usd:.2f} USD 超过上限 {max_usd:.2f} USD，任务已停止",
                    )
                    return

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
