"""报告中心接口（API.md §3.11）：列表 / 详情 / 样本明细 / Markdown 导出 / 免登分享 / 基线冻结。

报告行由 Worker 在评测任务成功后写入；详情支持登录 Cookie 或未过期 ?share= 免登访问。
benchmark 样本明细来自 Worker 落库的 ``eval_items``；RAG/stress 段暂未开放，
前端在无数据时必须展示空态/错误态，禁止用静态报告顶替（API.md §12.3）。
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_current_user_optional
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Dataset, EvalItem, ProtocolProfile, Report, Task, User

router = APIRouter(prefix="/api/reports", tags=["reports"])

_KIND_LABELS = {
    "benchmark": "Benchmark 报告",
    "rag": "RAG 评测报告",
    "stress": "共享压测报告",
    "testcase": "用例生成报告",
}


def _child_stress_report_id(db: Session, task: Task | None) -> str | None:
    """先评后压：质量任务派生的压测子任务所对应的报告 ID。"""
    if not task:
        return None
    child = (
        db.query(Task)
        .filter(Task.parent_task_id == task.id, Task.kind == "stress")
        .order_by(Task.created_at.asc())
        .first()
    )
    if not child:
        return None
    child_report = db.query(Report).filter(Report.task_id == child.id).first()
    return child_report.id if child_report else None


def _parent_report_id(db: Session, task: Task | None) -> str | None:
    """压测任务回溯父质量任务的报告 ID。"""
    if not task or not task.parent_task_id:
        return None
    parent_report = db.query(Report).filter(Report.task_id == task.parent_task_id).first()
    return parent_report.id if parent_report else None


def _title(db: Session, report: Report, task: Task | None) -> str:
    """按契约示例风格生成报告标题：<类型> · <数据集 版本>（可解析时）。"""
    label = _KIND_LABELS.get(report.kind, f"{report.kind} 报告")
    config = (task.config or {}) if task else {}
    dataset_id = config.get("dataset_id")
    if dataset_id:
        ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if ds:
            return f"{label} · {ds.name} v{ds.version}"
    return f"{label} · 任务 {report.task_id[:8]}"


def _report_json(db: Session, report: Report) -> dict:
    """装配契约公共头；metrics JSONB 原样展开，富字段（scores/sample_items 等）随执行器落地自动透出。"""
    task = db.query(Task).filter(Task.id == report.task_id).first()
    body = {
        "id": report.id,
        "task_id": report.task_id,
        "child_stress_report_id": _child_stress_report_id(db, task),
        "parent_report_id": _parent_report_id(db, task),
        "kind": report.kind,
        "title": _title(db, report, task),
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "snapshot": (task.config or {}) if task else {},
        # 基线冻结后 baseline_id 指向本报告，供同数据集版本 + 主指标对比 Δ
        "baseline_id": report.id if report.is_baseline else None,
        "degraded": False,
    }
    # metrics 内的富字段（scores / rag_scores / qps_peak ...）平铺到顶层，与契约详情结构对齐
    if isinstance(report.metrics, dict):
        body.update(report.metrics)
    return body


def _report_markdown(db: Session, report: Report) -> str:
    """最小 Markdown 导出：标题 + 公共头 + metrics 键值表。"""
    data = _report_json(db, report)
    lines = [
        f"# {data['title']}",
        "",
        f"- 报告 ID：`{report.id}`",
        f"- 关联任务：`{report.task_id}`",
        f"- 类型：{report.kind}",
        f"- 生成时间：{data['created_at'] or '—'}",
        "",
        "## 指标",
        "",
        "| 键 | 值 |",
        "| --- | --- |",
    ]
    metrics = report.metrics if isinstance(report.metrics, dict) else {}
    if metrics:
        for key, value in metrics.items():
            lines.append(f"| {key} | {value} |")
    else:
        lines.append("| — | 暂无指标数据 |")
    return "\n".join(lines) + "\n"


@router.get("")
def list_reports(
    kind: str | None = None,
    task_id: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """报告列表：支持 kind / task_id 过滤与分页，按创建时间倒序。"""
    query = db.query(Report)
    if kind:
        query = query.filter(Report.kind == kind)
    if task_id:
        query = query.filter(Report.task_id == task_id)
    total = query.count()
    rows = query.order_by(Report.created_at.desc()).offset(offset).limit(limit).all()
    items = []
    for row in rows:
        task = db.query(Task).filter(Task.id == row.task_id).first()
        items.append(
            {
                "id": row.id,
                "title": _title(db, row, task),
                "kind": row.kind,
                "task_id": row.task_id,
                "child_stress_report_id": _child_stress_report_id(db, task),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"items": items, "total": total}


@router.get("/{report_id}")
def get_report(
    report_id: str,
    fmt: str | None = None,
    share: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """报告详情；登录 Cookie 或未过期 `?share=` 免登访问；`?fmt=md` 导出 Markdown。"""
    if user is None and not share:
        # 未登录且未携带分享令牌：查库前直接拒绝
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事", status_code=401)
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在或已删除")
    if user is None:
        # 免登分享通道：token 匹配且未过期才放行只读详情
        token_valid = (
            report.share_token
            and secrets.compare_digest(report.share_token, share or "")
            and report.share_expire_at
            and report.share_expire_at > datetime.now(UTC)
        )
        if not token_valid:
            raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事", status_code=401)
    if fmt == "md":
        return PlainTextResponse(_report_markdown(db, report), media_type="text/markdown; charset=utf-8")
    return _report_json(db, report)


@router.get("/{report_id}/samples")
def report_samples(
    report_id: str,
    filter: str = Query(default="all", pattern="^(all|diff|fail)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """样本级逐题比对（API §3.11）：按行聚合各 profile 预测，支持 all/diff/fail 过滤。

    数据全部来自 Worker 写入的 ``eval_items``（含 Raw 报文，超 32KB 已截断），
    浏览器只做只读回放；非 benchmark 报告暂未提供样本明细，返回空集与说明。
    """
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在或已删除")
    if report.kind != "benchmark":
        return {"items": [], "total": 0, "note": "该类型报告暂未提供样本明细"}

    items = (
        db.query(EvalItem)
        .filter(EvalItem.task_id == report.task_id)
        .order_by(EvalItem.row_no.asc(), EvalItem.profile_id.asc())
        .all()
    )
    profile_ids = {item.profile_id for item in items}
    profiles = {
        profile.id: profile
        for profile in db.query(ProtocolProfile).filter(ProtocolProfile.id.in_(profile_ids)).all()
    }

    # 按行号聚合为逐题比对条目（行数上限 2 万，内存聚合可控）
    grouped: dict[int, list[EvalItem]] = {}
    for item in items:
        grouped.setdefault(item.row_no, []).append(item)

    rows: list[dict[str, Any]] = []
    for row_no, predictions in grouped.items():
        scores = [p.score for p in predictions if p.score is not None]
        # 差异行：各 profile 得分不全一致，或部分成功部分失败
        diff = len({round(s, 6) for s in scores}) > 1 or (
            any(p.error for p in predictions) and scores
        )
        has_fail = any(p.error for p in predictions) or (scores and all(s == 0 for s in scores))
        if filter == "fail" and not has_fail:
            continue
        if filter == "diff" and not diff:
            continue
        rows.append(
            {
                "row_no": row_no,
                "question": predictions[0].question,
                "reference": predictions[0].reference,
                "context": predictions[0].context,
                "diff": diff,
                "predictions": [
                    {
                        "profile_id": p.profile_id,
                        "profile_name": profiles[p.profile_id].name if p.profile_id in profiles else None,
                        "model": profiles[p.profile_id].model if p.profile_id in profiles else None,
                        "output": p.output,
                        "score": p.score,
                        "exact": p.exact,
                        "rouge_l": p.rouge_l,
                        "latency_ms": p.latency_ms,
                        "error": p.error,
                        "raw": p.raw,
                    }
                    for p in predictions
                ],
            }
        )

    rows.sort(key=lambda entry: entry["row_no"])
    total = len(rows)
    return {"items": rows[offset : offset + limit], "total": total}


@router.post("/{report_id}/share")
def share_report(
    report_id: str,
    body: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """生成免登只读分享链接：默认 7 天有效，token 仅本次响应返回、列表不回显。"""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在或已删除")
    days = (body or {}).get("expire_days", 7)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
        raise AppError(ErrorCode.VALIDATION, "分享有效期须为 1–30 天的整数")
    token = secrets.token_urlsafe(24)
    report.share_token = token
    report.share_expire_at = datetime.now(UTC) + timedelta(days=days)
    db.commit()
    return {
        "token": token,
        "url": f"/reports/{report.id}?share={token}",
        "expires_at": report.share_expire_at.isoformat(),
    }


@router.post("/{report_id}/baseline")
def freeze_baseline(
    report_id: str,
    request: Request,
    body: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """冻结/解冻当前报告为对比基线；按契约写 baseline_freeze / baseline_unfreeze 审计。"""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在或已删除")
    frozen = bool((body or {}).get("frozen", True))
    report.is_baseline = frozen
    db.add(
        AuditLog(
            user_id=user.id,
            action="baseline_freeze" if frozen else "baseline_unfreeze",
            target_type="report",
            target_id=report.id,
            detail={"task_id": report.task_id},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    return {"frozen": report.is_baseline, "task_id": report.task_id}
