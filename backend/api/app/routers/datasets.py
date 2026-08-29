"""数据集工作台路由（API V1.3 §3.7）。

包含两组 router：
- ``router``：/api/datasets 数据集 CRUD、数据行读写与 AI 候选生成；
- ``folders_router``：/api/dataset-folders 目录树管理（在 main.py 单独注册）。

数据行扩展列值持久化到 DatasetRow.extras；AI 候选生成只返回不落库，
前端人工删改后必须再经 PUT /api/datasets/{id}/rows 保存。
"""

import csv
import hashlib
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi import Request as FastApiRequest
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..llm_client import call_agent_model, extract_json_array
from ..models import (
    AuditLog,
    Dataset,
    DatasetFolder,
    DatasetImport,
    DatasetImportRow,
    DatasetRow,
    DatasetVersionRow,
    User,
)
from ..schemas import (
    AiGenerateIn,
    DatasetCreate,
    DatasetOut,
    DatasetRowIn,
    DatasetUpdate,
    FolderIn,
    FolderOut,
    RowsPayload,
    StagingRowsSave,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
folders_router = APIRouter(prefix="/api/dataset-folders", tags=["dataset-folders"])

# 行响应的固定字段键；扩展列同名键不写入 extras，避免平铺时覆盖固定字段
_RESERVED_EXTRA_KEYS = {
    "id",
    "dataset_id",
    "row_no",
    "question",
    "reference",
    "context",
    "pending_complete",
    "source_case_id",
    "q",
    "r",
    "c",
}

def _request_ip(request: FastApiRequest) -> str | None:
    """提取审计日志的请求来源 IP。"""
    return request.client.host if request.client else None


def _get_dataset_or_404(db: Session, dataset_id: str) -> Dataset:
    """读取数据集或抛出 NOT_FOUND。"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise AppError(ErrorCode.NOT_FOUND, "数据集不存在")
    return dataset


def _get_folder_or_404(db: Session, folder_id: str) -> DatasetFolder:
    """读取目录或抛出 NOT_FOUND。"""
    folder = db.query(DatasetFolder).filter(DatasetFolder.id == folder_id).first()
    if not folder:
        raise AppError(ErrorCode.NOT_FOUND, "目录不存在")
    return folder


def _assert_folder_exists(db: Session, folder_id: str) -> None:
    """校验挂载目标目录存在，不存在按入参错误 VALIDATION 处理。"""
    if not db.query(DatasetFolder).filter(DatasetFolder.id == folder_id).first():
        raise AppError(ErrorCode.VALIDATION, "目标目录不存在")


def _row_to_item(row: DatasetRow) -> dict[str, Any]:
    """把行记录展开为契约行项：固定字段 + extras 扩展键平铺。"""
    item: dict[str, Any] = {
        "row_no": row.row_no,
        "question": row.question or "",
        "reference": row.reference or "",
        "context": row.context,
        "pending_complete": bool(row.pending_complete),
        "source_case_id": row.source_case_id,
    }
    item.update(row.extras or {})
    return item


def _staging_row_to_item(row: DatasetImportRow) -> dict[str, Any]:
    """展开 staging 行并保留稳定 ID，供审核端编辑和精确选择发布。"""
    item: dict[str, Any] = {
        "id": row.id,
        "row_no": row.row_no,
        "question": row.question,
        "reference": row.reference,
        "context": row.context,
        "row_status": row.row_status,
        "warnings": row.warnings or [],
        "provenance": row.provenance or {},
    }
    item.update(row.extras or {})
    return item


def _version_row_to_item(row: DatasetVersionRow) -> dict[str, Any]:
    """读取不可变版本行时维持数据集表格字段，避免退回可编辑 DatasetRow。"""
    item: dict[str, Any] = {
        "row_no": row.row_no,
        "question": row.question,
        "reference": row.reference,
        "context": row.context,
        "pending_complete": not row.question.strip() or not row.reference.strip(),
    }
    item.update(row.extras or {})
    return item


def _content_sha256(
    question: str, reference: str, context: str | None, extras: dict[str, Any]
) -> str:
    """为 staging 编辑后的规范化内容重算行哈希，供发布版本内容校验。"""
    payload = json.dumps(
        {"question": question, "reference": reference, "context": context, "extras": extras},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_independent_staging_reviewer(job: DatasetImport, user: User) -> None:
    """staging 内容只能由非提报成员审核修订，避免提交人自行改变待审样本。"""
    if job.created_by == user.id:
        raise AppError(ErrorCode.VALIDATION, "提报成员不能编辑自己的 staging 导入")


def _refresh_dataset_counters(db: Session, dataset: Dataset) -> None:
    """按 dataset_rows 实况重算数据集行数与待补全行数。"""
    rows = db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id).all()
    dataset.row_count = len(rows)
    dataset.pending_complete_count = sum(1 for row in rows if row.pending_complete)


def _upsert_row(db: Session, dataset: Dataset, row_in: DatasetRowIn, row: DatasetRow | None) -> DatasetRow:
    """按 row_no 更新或插入单行；已有行上未提供的 q/r/c 保留原值。"""
    provided = row_in.model_fields_set
    if row is None:
        row = DatasetRow(
            dataset_id=dataset.id,
            row_no=row_in.row_no,
            question=row_in.q or "",
            reference=row_in.r or "",
            context=row_in.c,
        )
        db.add(row)
    else:
        if "q" in provided:
            row.question = row_in.q or ""
        if "r" in provided:
            row.reference = row_in.r or ""
        if "c" in provided:
            row.context = row_in.c
    if "source_case_id" in provided:
        row.source_case_id = row_in.source_case_id
    extras = {k: v for k, v in (row_in.model_extra or {}).items() if k not in _RESERVED_EXTRA_KEYS}
    if extras:
        merged = dict(row.extras or {})
        merged.update(extras)
        row.extras = merged
    # question / reference 任一缺失即视为待补全，评分时不计入分母
    row.pending_complete = not (row.question or "").strip() or not (row.reference or "").strip()
    return row


@router.get("")
def list_datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出全部数据集，按契约返回 {items, total} 包装。"""
    rows = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
    return {"items": [DatasetOut.model_validate(row) for row in rows], "total": len(rows)}


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(
    body: DatasetCreate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建空数据集，默认评判口径 contain。"""
    dataset = Dataset(name=body.name, metric=body.metric, created_by=user.id)
    db.add(dataset)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="dataset_create",
            target_type="dataset",
            target_id=dataset.id,
            detail={"name": dataset.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(dataset)
    return dataset


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取单个数据集详情。"""
    return _get_dataset_or_404(db, dataset_id)


@router.put("/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: str,
    body: DatasetUpdate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按提供的字段更新数据集；column_schema 整体替换，已有报告不受影响。"""
    dataset = _get_dataset_or_404(db, dataset_id)
    values = body.model_dump(exclude_unset=True)
    if "folder_id" in values:
        folder_id = values.pop("folder_id")
        if folder_id is not None:
            _assert_folder_exists(db, folder_id)
        dataset.folder_id = folder_id
    if "column_schema" in values:
        dataset.column_schema = values.pop("column_schema")
    for field, value in values.items():
        setattr(dataset, field, value)
    db.add(
        AuditLog(
            user_id=user.id,
            action="dataset_update",
            target_type="dataset",
            target_id=dataset.id,
            detail={"name": dataset.name, "fields": sorted(body.model_fields_set)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(dataset)
    return dataset


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除数据集并级联清理其数据行；进行中的历史任务快照不受影响。"""
    dataset = _get_dataset_or_404(db, dataset_id)
    if dataset.active_version_id:
        raise AppError(ErrorCode.VALIDATION, "含已发布版本的数据集不可直接删除")
    db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset_id).delete(synchronize_session=False)
    db.delete(dataset)
    db.add(
        AuditLog(
            user_id=user.id,
            action="dataset_delete",
            target_type="dataset",
            target_id=dataset_id,
            detail={"name": dataset.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    return {"ok": True}


# 上传契约上限：≤50MB、≤2 万行（API.md §3.7）
_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
_UPLOAD_MAX_ROWS = 20_000


def _parse_upload_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    """解析 JSONL / CSV 上传内容为行字典列表；非法结构整文件拒绝（VALIDATION）。"""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(ErrorCode.VALIDATION, "文件必须为 UTF-8 编码") from None
    rows: list[dict[str, Any]] = []
    if filename.lower().endswith(".jsonl"):
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                raise AppError(ErrorCode.VALIDATION, f"第 {line_no} 行不是合法 JSON") from None
            if not isinstance(obj, dict):
                raise AppError(ErrorCode.VALIDATION, f"第 {line_no} 行必须为 JSON 对象")
            rows.append(obj)
    elif filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "question" not in reader.fieldnames or "reference" not in reader.fieldnames:
            raise AppError(ErrorCode.VALIDATION, "CSV 必须包含 question,reference 列（context 可选）")
        rows.extend(dict(row) for row in reader)
    else:
        raise AppError(ErrorCode.VALIDATION, "仅支持 .jsonl 或 .csv 文件")
    if not rows:
        raise AppError(ErrorCode.VALIDATION, "文件内容为空")
    if len(rows) > _UPLOAD_MAX_ROWS:
        raise AppError(ErrorCode.VALIDATION, f"行数超过上限（{_UPLOAD_MAX_ROWS} 行）")
    return rows


@router.post("/{dataset_id}/upload")
async def upload_dataset_file(
    dataset_id: str,
    request: FastApiRequest,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """JSONL/CSV 全量覆盖导入：解析校验 → 替换全部数据行 → version+1 并重算计数。"""
    dataset = _get_dataset_or_404(db, dataset_id)
    if dataset.active_version_id:
        raise AppError(ErrorCode.VALIDATION, "已发布数据集只能通过受控导入产生新版本")
    content = await file.read()
    if len(content) > _UPLOAD_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "文件大小超过 50MB 上限")
    raw_rows = _parse_upload_rows(file.filename or "", content)

    # 全量覆盖：清空旧行后按新文件顺序重建 row_no
    db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id).delete(synchronize_session=False)
    for idx, raw in enumerate(raw_rows, start=1):
        question = str(raw.get("question") or raw.get("q") or "")
        reference = str(raw.get("reference") or raw.get("r") or "")
        context = raw.get("context") or raw.get("c")
        extras = {k: v for k, v in raw.items() if k not in _RESERVED_EXTRA_KEYS}
        db.add(
            DatasetRow(
                dataset_id=dataset.id,
                row_no=idx,
                question=question,
                reference=reference,
                context=str(context) if context is not None else None,
                extras=extras,
                pending_complete=not question.strip() or not reference.strip(),
            )
        )
    dataset.version += 1
    db.flush()
    _refresh_dataset_counters(db, dataset)
    db.add(
        AuditLog(
            user_id=user.id,
            action="dataset_upload",
            target_type="dataset",
            target_id=dataset.id,
            detail={"filename": file.filename, "row_count": dataset.row_count, "version": dataset.version},
            ip=_request_ip(request),
        )
    )
    db.commit()
    return {"version": dataset.version, "row_count": dataset.row_count}


@router.get("/{dataset_id}/rows")
def list_dataset_rows(
    dataset_id: str,
    pending_complete: bool | None = Query(default=None),
    view: str = Query(default="active"),
    import_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取正式行或指定导入 staging；staging 不会被评测 Worker 直接使用。"""
    _ = user
    dataset = _get_dataset_or_404(db, dataset_id)
    if view == "staging":
        if not import_id:
            raise AppError(ErrorCode.VALIDATION, "读取 staging 必须提供 import_id")
        job = (
            db.query(DatasetImport)
            .filter(DatasetImport.id == import_id, DatasetImport.dataset_id == dataset.id)
            .first()
        )
        if not job:
            raise AppError(ErrorCode.NOT_FOUND, "导入作业不存在")
        if job.status not in {"review_ready", "published", "rejected"}:
            raise AppError(ErrorCode.VALIDATION, "当前导入作业没有可审核的 staging")
        rows = (
            db.query(DatasetImportRow)
            .filter(DatasetImportRow.import_id == job.id)
            .order_by(DatasetImportRow.row_no.asc())
            .all()
        )
        return {
            "items": [_staging_row_to_item(row) for row in rows],
            "total": len(rows),
            "import_id": job.id,
            "staging_revision": job.staging_revision,
        }
    if view != "active":
        raise AppError(ErrorCode.VALIDATION, "view 仅支持 active 或 staging")
    if dataset.active_version_id:
        version_rows = (
            db.query(DatasetVersionRow)
            .filter(DatasetVersionRow.dataset_version_id == dataset.active_version_id)
            .order_by(DatasetVersionRow.row_no.asc())
            .all()
        )
        return {
            "items": [_version_row_to_item(row) for row in version_rows],
            "total": len(version_rows),
        }
    query = db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id)
    if pending_complete:
        query = query.filter(DatasetRow.pending_complete.is_(True))
    rows = query.order_by(DatasetRow.row_no.asc()).all()
    return {"items": [_row_to_item(row) for row in rows], "total": len(rows)}


@router.put("/{dataset_id}/rows")
def save_dataset_rows(
    dataset_id: str,
    body: StagingRowsSave | RowsPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    view: str = "active",
    import_id: str | None = None,
):
    """保存手工正式行或审核 staging；两者使用不同的并发与删除语义。"""
    dataset = _get_dataset_or_404(db, dataset_id)
    if view == "staging":
        if not import_id or not isinstance(body, StagingRowsSave):
            raise AppError(
                ErrorCode.VALIDATION, "保存 staging 必须提供 import_id、revision 和稳定行 ID"
            )
        job = (
            db.query(DatasetImport)
            .filter(DatasetImport.id == import_id, DatasetImport.dataset_id == dataset.id)
            .with_for_update()
            .first()
        )
        if not job:
            raise AppError(ErrorCode.NOT_FOUND, "导入作业不存在")
        _require_independent_staging_reviewer(job, user)
        if job.status != "review_ready" or job.staging_revision != body.expected_staging_revision:
            raise AppError(ErrorCode.CONCURRENCY, "staging 已变化、未就绪或已发布，请刷新后重试")
        row_ids = [str(raw.get("id") or "") for raw in body.rows]
        if not all(row_ids) or len(row_ids) != len(set(row_ids)):
            raise AppError(ErrorCode.VALIDATION, "每个 staging 行必须提供唯一稳定 id")
        rows = (
            db.query(DatasetImportRow)
            .filter(
                DatasetImportRow.import_id == job.id,
                DatasetImportRow.id.in_(row_ids),
                DatasetImportRow.row_status == "staging",
            )
            .all()
        )
        if len(rows) != len(row_ids):
            raise AppError(ErrorCode.VALIDATION, "存在无效、重复或不可编辑的 staging 行")
        by_id = {row.id: row for row in rows}
        for raw in body.rows:
            row = by_id[str(raw["id"])]
            question = str(raw.get("q", raw.get("question", row.question)) or "")
            reference = str(raw.get("r", raw.get("reference", row.reference)) or "")
            context_raw = raw.get("c", raw.get("context", row.context))
            context = str(context_raw) if context_raw is not None else None
            extras = {
                key: value
                for key, value in raw.items()
                if key
                not in {
                    "id",
                    "row_no",
                    "q",
                    "r",
                    "c",
                    "question",
                    "reference",
                    "context",
                    "row_status",
                    "warnings",
                    "provenance",
                }
            }
            row.question = question
            row.reference = reference
            row.context = context
            row.extras = extras
            row.content_sha256 = _content_sha256(question, reference, context, extras)
        job.staging_revision += 1
        db.add(
            AuditLog(
                user_id=user.id,
                action="dataset_import_staging_save",
                target_type="dataset_import",
                target_id=job.id,
                detail={"dataset_id": dataset.id, "staging_revision": job.staging_revision},
            )
        )
        db.commit()
        rows = (
            db.query(DatasetImportRow)
            .filter(DatasetImportRow.import_id == job.id)
            .order_by(DatasetImportRow.row_no.asc())
            .all()
        )
        return {
            "items": [_staging_row_to_item(row) for row in rows],
            "total": len(rows),
            "import_id": job.id,
            "staging_revision": job.staging_revision,
        }
    if view != "active" or not isinstance(body, RowsPayload):
        raise AppError(ErrorCode.VALIDATION, "view 仅支持 active 或 staging")
    _ = user
    if dataset.active_version_id:
        raise AppError(ErrorCode.VALIDATION, "已发布数据集只能通过受控导入产生新版本")
    existing = {
        row.row_no: row
        for row in db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id).all()
    }
    # 当前视图保存语义：载荷中未包含的现有行视为已删除（前端批量删除行依赖此行为）
    payload_row_nos = {row_in.row_no for row_in in body.rows}
    for row_no, row in existing.items():
        if row_no not in payload_row_nos:
            db.delete(row)
    for row_in in body.rows:
        _upsert_row(db, dataset, row_in, existing.get(row_in.row_no))
    db.flush()
    _refresh_dataset_counters(db, dataset)
    db.commit()
    rows = (
        db.query(DatasetRow)
        .filter(DatasetRow.dataset_id == dataset.id)
        .order_by(DatasetRow.row_no.asc())
        .all()
    )
    return {"items": [_row_to_item(row) for row in rows], "total": len(rows)}


@router.post("/ai-generate")
def ai_generate_rows(
    body: AiGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按模式调用 Agent 协议档生成候选问答样本；候选不落库，前端确认后经 rows 保存。"""
    _ = user
    mode = body.mode
    if mode not in {"scene", "seed", "doc", "fill_missing"}:
        raise AppError(ErrorCode.VALIDATION, "不支持的生成模式")

    temperature = body.temperature if body.temperature is not None else 0.5
    if mode == "fill_missing":
        if not body.rows:
            raise AppError(ErrorCode.VALIDATION, "fill_missing 模式需要提供待补全行 rows")
        user_prompt = (
            f"请补全以下评测样本中缺失的字段（question 问题 / reference 参考答案 / context 上下文），"
            f"已填写的字段保持原样，必须保留 row_no，最多补全 {body.max_count} 条。\n\n"
            f"样本：\n{json.dumps(body.rows, ensure_ascii=False)}"
        )
    else:
        if mode == "scene":
            material = "\n".join(
                part for part in (body.instruction, body.source_text) if part and part.strip()
            )
            hint = "请基于上述场景与要求，设计可评测的问答样本"
        elif mode == "seed":
            material = body.seed or ""
            hint = "请参考上述种子样本的主题、风格与难度，生成同类问答样本"
        else:  # doc
            material = body.source_text or ""
            hint = "请阅读上述文档，抽取可作为评测基准的知识点问答"
        if not material.strip():
            raise AppError(ErrorCode.VALIDATION, "该模式需要提供 instruction/source_text/seed 至少一项")
        user_prompt = (
            f"{hint}，生成不超过 {body.max_count} 条，每条含 question（问题）、"
            f"reference（参考答案）、context（上下文，可空），可附 tags/difficulty 等扩展字段。\n\n"
            f"参考材料：\n{material[:_SOURCE_MAX_CHARS]}"
        )

    result = call_agent_model(db, _AI_GENERATE_SYSTEM, user_prompt, temperature=temperature)
    data = extract_json_array(result.text)
    fallback_row_nos = [row.get("row_no") for row in body.rows] if mode == "fill_missing" else None
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        if not (item.get("question") or item.get("q")):
            continue
        rows.append(_normalize_generated_row(item, idx + 1, fallback_row_nos))
    if not rows:
        raise AppError(ErrorCode.UPSTREAM, "模型未返回有效问答样本，请调整输入后重试")
    return {"items": rows}


_SOURCE_MAX_CHARS = 20_000

_AI_GENERATE_SYSTEM = (
    "你是测试数据集生成专家，负责为 AI 评测设计高质量问答样本。"
    "只输出一个 JSON 数组，不要输出任何解释文字或 markdown 代码围栏；"
    "每条样本包含 question（问题）、reference（参考答案）、context（上下文，可空），"
    "可附加 tags、difficulty 等字段。"
)


def _normalize_generated_row(
    item: dict[str, Any], idx: int, fallback_row_nos: list[Any] | None = None
) -> dict[str, Any]:
    """把模型输出的一行归一化为前端可编辑行（q/r/c + 扩展键透传）。"""
    row_no = item.get("row_no")
    if row_no is None and fallback_row_nos and idx - 1 < len(fallback_row_nos):
        row_no = fallback_row_nos[idx - 1]
    row: dict[str, Any] = {
        "row_no": row_no or idx,
        "q": str(item.get("question") or item.get("q") or ""),
        "r": str(item.get("reference") or item.get("r") or ""),
        "c": item.get("context", item.get("c")),
    }
    for key in ("tags", "difficulty"):
        if item.get(key) is not None:
            row[key] = item[key]
    return row


@folders_router.get("")
def list_folders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按排序号返回全部目录节点，前端自行组装树。"""
    rows = (
        db.query(DatasetFolder)
        .order_by(DatasetFolder.sort_order.asc(), DatasetFolder.created_at.asc())
        .all()
    )
    return {"items": [FolderOut.model_validate(row) for row in rows], "total": len(rows)}


@folders_router.post("", response_model=FolderOut, status_code=201)
def create_folder(
    body: FolderIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建目录节点；parent_id 缺省表示根目录。"""
    if not body.name:
        raise AppError(ErrorCode.VALIDATION, "目录名称不能为空")
    if body.parent_id:
        _assert_folder_exists(db, body.parent_id)
    folder = DatasetFolder(
        name=body.name,
        parent_id=body.parent_id,
        sort_order=body.sort_order or 0,
    )
    db.add(folder)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="folder_create",
            target_type="dataset_folder",
            target_id=folder.id,
            detail={"name": folder.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(folder)
    return folder


@folders_router.put("/{folder_id}", response_model=FolderOut)
def update_folder(
    folder_id: str,
    body: FolderIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按提供的字段更新目录；移动时校验父目录存在且不构成环。"""
    folder = _get_folder_or_404(db, folder_id)
    values = body.model_dump(exclude_unset=True)
    if "parent_id" in values:
        parent_id = values.pop("parent_id")
        if parent_id is not None:
            _assert_folder_exists(db, parent_id)
            # 沿祖先链向上检查，防止把目录挂到自身或后代节点下形成环
            current = parent_id
            while current:
                if current == folder.id:
                    raise AppError(ErrorCode.VALIDATION, "不能把目录移动到自身或其子目录下")
                node = db.query(DatasetFolder).filter(DatasetFolder.id == current).first()
                current = node.parent_id if node else None
        folder.parent_id = parent_id
    for field, value in values.items():
        if value is not None:
            setattr(folder, field, value)
    db.add(
        AuditLog(
            user_id=user.id,
            action="folder_update",
            target_type="dataset_folder",
            target_id=folder.id,
            detail={"name": folder.name, "fields": sorted(body.model_fields_set)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(folder)
    return folder


@folders_router.delete("/{folder_id}")
def delete_folder(
    folder_id: str,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除空目录；仍含数据集或子目录时返回 VALIDATION。"""
    folder = _get_folder_or_404(db, folder_id)
    if db.query(DatasetFolder).filter(DatasetFolder.parent_id == folder.id).first():
        raise AppError(ErrorCode.VALIDATION, "目录下仍有子目录，无法删除")
    if db.query(Dataset).filter(Dataset.folder_id == folder.id).first():
        raise AppError(ErrorCode.VALIDATION, "目录下仍有数据集，无法删除")
    db.delete(folder)
    db.add(
        AuditLog(
            user_id=user.id,
            action="folder_delete",
            target_type="dataset_folder",
            target_id=folder_id,
            detail={"name": folder.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    return {"ok": True}
