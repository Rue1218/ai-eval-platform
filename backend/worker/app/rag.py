"""RAG 评测执行器（kind=rag）。

执行流程（PRD 5.2.2 / 3.9）：
1. 载入任务快照 → 知识库 → 黄金 QA 行（按 row_no 升序，sample_size 截断）；
2. 逐行 × 逐 rag_mode 检索 top-k，按黄金 QA 期望文档计算 hit_rate/mrr/recall/contain；
3. 每行落一条 ``eval_items``（profile_id=kb_id，score=首选 mode 的 hit_rate）；
4. 汇总写 ``reports``（kind=rag，含 per_mode 明细）并置 succeeded。

检索经 ``shared.kb`` 完成：LightRAG 服务可用时优先，空返回则回退本地关键词
检索兜底，保证 E2E 能产出真实报告；M3 替换 lightrag-hku 后无需改动本执行器。
本执行器不做 LLM 调用，不写 UsageLedger；answer_contain 采用「参考答案子串
出现在检索文本中」的文档包含判定。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from shared.kb import compute_metrics, retrieve

from .db import SessionLocal
from .events import push_ws
from .models import (
    EvalItem,
    GoldQa,
    GoldQaItem,
    KnowledgeBase,
    Report,
    Task,
    TaskEvent,
)
from .sampling import clamp_sample_size
from .stress_spawn import maybe_spawn_stress
from .task_state import claim_running_task_for_terminal_write, is_cancelled

logger = logging.getLogger("worker.rag")

DEFAULT_K = 5
DEFAULT_MODES = ["hybrid"]


def _now() -> datetime:
    """统一使用 UTC 时间戳。"""
    return datetime.now(UTC)


def _progress(db: Session, task: Task, done: int, total: int, message: str) -> None:
    """更新任务进度并推送 WS progress 事件。"""
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
        logger.info("rag task %s skipped failure because it is no longer running", task_id)
        return
    task.status = "failed"
    task.finished_at = _now()
    task.result = {**(task.result or {}), "error_code": code, "error_message": message}
    db.add(
        TaskEvent(
            task_id=task.id, event="error", level="error", message=message, payload={"code": code}
        )
    )
    db.commit()
    push_ws(task.session_id, "error", {"code": code, "message": message}, task_id=task.id)
    logger.warning("rag task %s failed (%s): %s", task.id, code, message)


def run_rag(task_id: str) -> None:
    """RAG 任务执行入口：检索黄金 QA 并计算检索质量指标。"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error("rag task %s not found, skip execution", task_id)
            return
        config = task.config or {}
        run = config.get("run") or {}
        kb_id = config.get("kb_id")
        gold_qa_id = config.get("gold_qa_id")
        modes = [m for m in (config.get("rag_mode") or []) if m] or DEFAULT_MODES
        k = run.get("k")
        k = int(k) if isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= 20 else DEFAULT_K

        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first() if kb_id else None
        if not kb:
            _fail(db, task, "VALIDATION", "关联知识库不存在，任务无法执行")
            return
        qa = db.query(GoldQa).filter(GoldQa.id == gold_qa_id).first() if gold_qa_id else None
        if not qa:
            _fail(db, task, "VALIDATION", "关联黄金 QA 集不存在，任务无法执行")
            return
        items = (
            db.query(GoldQaItem)
            .filter(GoldQaItem.gold_qa_id == qa.id)
            .order_by(GoldQaItem.row_no.asc())
            .all()
        )
        sample_size = clamp_sample_size(run.get("sample_size"), len(items))
        items = items[:sample_size]
        if not items:
            _fail(db, task, "VALIDATION", "黄金 QA 没有可评测的行")
            return

        total = len(items) * len(modes)
        done = 0
        # 逐 mode 聚合器：分母 = 有 expected_doc_ids 的行（无期望文档不进 Hit Rate 分母）
        agg = {
            mode: {
                "hit": 0.0,
                "mrr": 0.0,
                "recall": 0.0,
                "contain": 0.0,
                "hit_denominator": 0,
                "contain_denominator": 0,
            }
            for mode in modes
        }
        primary_mode = modes[0]

        for item in items:
            # P4-2 取消传播：逐条检查任务是否取消，提前停止不烧 token；
            # 终态写入另有 claim_running_task_for_terminal_write 行锁保护。
            if is_cancelled(db, task.id):
                logger.info("rag task %s cancelled mid-run (done=%s/%s), skip", task_id, done, total)
                break
            expected = list(item.expected_doc_ids or [])
            reference = item.reference or ""
            row_metrics: dict[str, dict] = {}
            row_contexts: list[str] = []
            start = time.perf_counter()
            for mode in modes:
                retrieved = retrieve(db, kb_id, item.question, mode=mode, k=k)
                metrics = compute_metrics(retrieved, expected, reference)
                row_metrics[mode] = metrics
                agg[mode]["hit"] += metrics["hit_rate"]
                agg[mode]["mrr"] += metrics["mrr"]
                agg[mode]["recall"] += metrics["recall"]
                agg[mode]["contain"] += metrics["contain"]
                if expected:
                    agg[mode]["hit_denominator"] += 1
                if reference:
                    agg[mode]["contain_denominator"] += 1
                if mode == primary_mode:
                    row_contexts = [item.get("text") or "" for item in retrieved[:k]]
            latency_ms = int((time.perf_counter() - start) * 1000)

            score = row_metrics.get(primary_mode, {}).get("hit_rate")
            db.add(
                EvalItem(
                    task_id=task.id,
                    profile_id=kb_id,
                    row_no=item.row_no,
                    question=item.question,
                    reference=reference,
                    context="\n---\n".join(row_contexts) or None,
                    output=json.dumps({"modes": row_metrics}, ensure_ascii=False),
                    score=score,
                    latency_ms=latency_ms,
                )
            )
            done += len(modes)
            if done % 20 == 0 or done >= total:
                db.commit()
                _progress(db, task, done, total, "检索评估中")

        db.commit()

        # ─── 汇总出报告 ───
        per_mode: dict[str, dict] = {}
        for mode, acc in agg.items():
            hd = acc["hit_denominator"]
            cd = acc["contain_denominator"]
            per_mode[mode] = {
                "hit_rate_at_k": round(acc["hit"] / hd, 4) if hd else 0.0,
                "mrr": round(acc["mrr"] / hd, 4) if hd else 0.0,
                "recall_at_k": round(acc["recall"] / hd, 4) if hd else 0.0,
                "answer_contain": round(acc["contain"] / cd, 4) if cd else 0.0,
                "hit_denominator": hd,
                "contain_denominator": cd,
            }
        overall = per_mode[primary_mode]

        report = Report(
            task_id=task.id,
            kind="rag",
            metrics={
                "kb_id": kb_id,
                "kb_name": kb.name,
                "gold_qa_id": qa.id,
                "gold_qa_name": qa.name,
                "gold_qa_version": qa.version,
                "k": k,
                "modes": modes,
                "hit_rate_at_k": overall["hit_rate_at_k"],
                "mrr": overall["mrr"],
                "recall_at_k": overall["recall_at_k"],
                "answer_contain": overall["answer_contain"],
                "hit_denominator_note": "无 expected_doc_ids 的样本不进 Hit Rate 分母",
                "per_mode": per_mode,
                "sample_total": len(items),
                "degraded": None,
            },
        )
        db.add(report)
        db.flush()

        task = claim_running_task_for_terminal_write(db, task.id)
        if not task:
            logger.info("rag task %s skipped finish because it is no longer running", task_id)
            return
        task.status = "succeeded"
        task.finished_at = _now()
        task.report_id = report.id
        task.result = {"kind": "rag", "samples": len(items)}
        db.add(TaskEvent(task_id=task.id, event="finish", payload={"status": "succeeded"}))
        db.commit()
        push_ws(
            task.session_id,
            "progress",
            {"percent": 100, "done": total, "total": total, "message": "任务已完成"},
            task_id=task.id,
        )
        logger.info("rag task %s succeeded (samples=%s modes=%s)", task.id, len(items), modes)
        maybe_spawn_stress(db, task)
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag task %s unexpected failure", task_id)
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task and task.status in {"queued", "running"}:
                _fail(db, task, "INTERNAL", f"RAG 评测异常({type(exc).__name__})")
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
