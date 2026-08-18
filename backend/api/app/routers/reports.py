"""报告中心只读接口（API.md §3.11）：列表 / 详情 / Markdown 导出。

报告行由 Worker 在评测任务成功后写入；本路由只做只读装配，不产生任何写操作。
samples / share / baseline 属 M2 后续里程碑，暂未开放；前端在无数据时必须展示
空态/错误态，禁止用静态报告顶替（API.md §12.3）。
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import Dataset, Report, Task, User

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
        "baseline_id": None,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """报告详情；`?fmt=md` 时以 text/markdown 返回导出文本。"""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppError(ErrorCode.NOT_FOUND, "报告不存在或已删除")
    if fmt == "md":
        return PlainTextResponse(_report_markdown(db, report), media_type="text/markdown; charset=utf-8")
    return _report_json(db, report)
