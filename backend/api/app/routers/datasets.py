"""数据集工作台路由（API V1.3 §3.7）。

包含两组 router：
- ``router``：/api/datasets 数据集 CRUD、数据行读写与 AI 候选生成；
- ``folders_router``：/api/dataset-folders 目录树管理（在 main.py 单独注册）。

数据行扩展列值持久化到 DatasetRow.extras；AI 候选生成只返回不落库，
前端人工删改后必须再经 PUT /api/datasets/{id}/rows 保存。
"""

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi import Request as FastApiRequest
from sqlalchemy.orm import Session

from ..agent.persona import page_ai_system
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..llm import call_agent_model, parse_json_candidates
from ..models import AuditLog, Dataset, DatasetFolder, DatasetRow, User
from ..schemas import (
    AiGenerateIn,
    DatasetCreate,
    DatasetOut,
    DatasetRowIn,
    DatasetUpdate,
    FolderIn,
    FolderOut,
    RowsPayload,
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

# 非 fill_missing 的三种生成模式中文描述，用于 prompt 组装
_AI_MODE_DESC = {
    "scene": "按场景描述生成",
    "seed": "按种子样本扩写",
    "doc": "从 PRD / 参考文档中提取",
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


def _build_ai_prompts(dataset: Dataset, body: AiGenerateIn) -> tuple[str, str]:
    """组装候选生成的中文 system / user prompt。"""
    columns = dataset.column_schema or []
    column_desc = "、".join(f"{col.get('key')}（{col.get('name')}）" for col in columns) or "无"
    system = page_ai_system(
        "你是评测数据集构建助手，负责为大模型评测数据集生成候选数据行。"
        "每行必须包含 q（问题）、r（标准答案）、c（上下文，可为 null）三个字段，"
        f"并可按需包含以下扩展列字段：{column_desc}。"
        "只输出一个 JSON 数组，不要输出任何解释文字或 markdown 代码围栏。"
    )
    if body.mode == "fill_missing":
        rows_text = json.dumps(body.rows, ensure_ascii=False, indent=2)
        user_prompt = (
            "以下是数据集中待补全的行（JSON 数组），请补全每行缺失的字段后原样返回：\n"
            f"{rows_text}\n"
            "要求：保留每行已有的 row_no 与非空字段不变，仅补全缺失或为空字符串的字段；"
            "输出仍是 JSON 数组，行数与输入一致。"
        )
        return system, user_prompt
    sections = [
        f"生成模式：{_AI_MODE_DESC[body.mode]}。",
        f"目标数据集：{dataset.name}（评判口径 {dataset.metric}）。",
    ]
    if body.instruction:
        sections.append(f"场景/指令：{body.instruction}")
    if body.seed:
        sections.append(f"种子样本：\n{body.seed}")
    if body.source_text:
        sections.append(f"参考文档：\n{body.source_text}")
    sections.append(f"请生成不超过 {body.max_count} 行候选数据。")
    return system, "\n\n".join(sections)


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取数据行；pending_complete=true 仅返回待补全行，false/缺省返回全部。"""
    dataset = _get_dataset_or_404(db, dataset_id)
    query = db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id)
    if pending_complete:
        query = query.filter(DatasetRow.pending_complete.is_(True))
    rows = query.order_by(DatasetRow.row_no.asc()).all()
    return {"items": [_row_to_item(row) for row in rows], "total": len(rows)}


@router.put("/{dataset_id}/rows")
def save_dataset_rows(
    dataset_id: str,
    body: RowsPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按 row_no 批量 upsert 数据行与扩展列，保存后重算行数与待补全数。"""
    dataset = _get_dataset_or_404(db, dataset_id)
    existing = {
        row.row_no: row
        for row in db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id).all()
    }
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
    """生成未落库候选行；前端人工删改后经 PUT rows 保存，本接口不写数据集版本。"""
    dataset = _get_dataset_or_404(db, body.dataset_id)
    system, user_prompt = _build_ai_prompts(dataset, body)
    text = call_agent_model(db, system, user_prompt)
    items = parse_json_candidates(text)
    if body.mode != "fill_missing":
        # 模型超量输出时截断到 max_count；fill_missing 行数必须与输入一致，不截断
        items = items[: body.max_count]
    return {"items": items}


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
