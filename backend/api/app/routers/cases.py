"""用例工作台路由（API V1.3 §3.8）。

包含两组 router：
- ``router``：/api/case-sets 用例集 CRUD、用例行批量保存、确认/废弃/映射、
  AI 候选生成与行级补全、xlsx/xmind 导出；
- ``folders_router``：/api/case-folders 用例目录树管理（在 main.py 单独注册）。

AI 候选生成（ai-generate）与行级补全（ai-fill）只返回未落库候选，前端人工
确认后必须再经 PUT /api/case-sets/{id}/cases 保存；confirmed 用例集为版本
快照，任何写操作一律拒绝。expires_at 由任务域在关联任务进入
awaiting_case_confirm 时写入（+72h），本域不主动维护。
"""

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query, Response
from fastapi import Request as FastApiRequest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..llm import call_agent_model, parse_json_candidates
from ..models import (
    AuditLog,
    CaseFolder,
    CaseItem,
    CaseSet,
    Dataset,
    DatasetRow,
    StoredFile,
    Task,
    User,
    utcnow,
    uuid_str,
)
from ..schemas import (
    CaseAiFillIn,
    CaseAiGenerateIn,
    CaseCancelIn,
    CaseConfirmIn,
    CaseIn,
    CaseMapIn,
    CaseSetCreate,
    CaseSetDetailOut,
    CaseSetOut,
    CaseSetUpdate,
    CasesPayload,
    FolderIn,
    FolderOut,
)

router = APIRouter(prefix="/api/case-sets", tags=["case-sets"])
folders_router = APIRouter(prefix="/api/case-folders", tags=["case-folders"])

# 用例行响应的固定字段键；扩展列同名键不写入 extras，避免平铺时覆盖固定字段
_RESERVED_EXTRA_KEYS = {
    "id",
    "case_set_id",
    "strategy",
    "priority",
    "module",
    "name",
    "precondition",
    "steps",
    "expected",
    "test_type",
    "mapped",
    "pending_complete",
    "extras",
    "sort_order",
    "created_at",
    "updated_at",
}

# 6 大策略英文键 -> 中文策略名；默认配比对齐 API §3.8（正向40/反向25/边界15/等价类10/状态迁移5/场景5）
_STRATEGY_NAMES = {
    "positive": "正向",
    "negative": "反向",
    "boundary": "边界",
    "equivalence": "等价类",
    "state": "状态迁移",
    "scenario": "场景",
}
_DEFAULT_STRATEGY_WEIGHTS = {
    "positive": 40,
    "negative": 25,
    "boundary": 15,
    "equivalence": 10,
    "state": 5,
    "scenario": 5,
}

# 来源文档注入 prompt 的最大字符数，防止超大文档撑爆模型上下文
_SOURCE_DOC_MAX_CHARS = 20_000

# 导出 Excel 的固定列：字段名 -> 中文列名；扩展列追加在其后
_EXPORT_FIXED_COLUMNS = [
    ("strategy", "策略"),
    ("priority", "优先级"),
    ("module", "模块"),
    ("name", "用例名称"),
    ("precondition", "前置条件"),
    ("steps", "步骤"),
    ("expected", "预期结果"),
    ("test_type", "测试类型"),
    ("mapped", "已映射"),
    ("pending_complete", "待补全"),
]
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_XMIND_MEDIA_TYPE = "application/vnd.xmind.workbook"


def _request_ip(request: FastApiRequest) -> str | None:
    """提取审计日志的请求来源 IP。"""
    return request.client.host if request.client else None


def _get_case_set_or_404(db: Session, set_id: str) -> CaseSet:
    """读取用例集或抛出 NOT_FOUND。"""
    case_set = db.query(CaseSet).filter(CaseSet.id == set_id).first()
    if not case_set:
        raise AppError(ErrorCode.NOT_FOUND, "用例集不存在")
    return case_set


def _get_folder_or_404(db: Session, folder_id: str) -> CaseFolder:
    """读取目录或抛出 NOT_FOUND。"""
    folder = db.query(CaseFolder).filter(CaseFolder.id == folder_id).first()
    if not folder:
        raise AppError(ErrorCode.NOT_FOUND, "目录不存在")
    return folder


def _assert_folder_exists(db: Session, folder_id: str) -> None:
    """校验挂载目标目录存在，不存在按入参错误 VALIDATION 处理。"""
    if not db.query(CaseFolder).filter(CaseFolder.id == folder_id).first():
        raise AppError(ErrorCode.VALIDATION, "目标目录不存在")


def _assert_editable(case_set: CaseSet) -> None:
    """confirmed 用例集为版本快照，任何写操作一律拒绝。"""
    if case_set.status == "confirmed":
        raise AppError(ErrorCode.VALIDATION, "已确认的用例集不可修改")


def _case_to_item(case: CaseItem) -> dict[str, Any]:
    """把用例行展开为契约用例项：固定字段 + extras 扩展键平铺。"""
    item: dict[str, Any] = {
        "id": case.id,
        "strategy": case.strategy,
        "priority": case.priority,
        "module": case.module or "",
        "name": case.name,
        "precondition": case.precondition or "",
        "steps": case.steps or "",
        "expected": case.expected or "",
        "test_type": case.test_type or "",
        "mapped": bool(case.mapped),
        "pending_complete": bool(case.pending_complete),
    }
    item.update(case.extras or {})
    return item


def _list_cases(db: Session, case_set: CaseSet) -> list[CaseItem]:
    """按排序号与创建时间返回用例集内全部用例行。"""
    return (
        db.query(CaseItem)
        .filter(CaseItem.case_set_id == case_set.id)
        .order_by(CaseItem.sort_order.asc(), CaseItem.created_at.asc())
        .all()
    )


def _refresh_generated_count(db: Session, case_set: CaseSet) -> None:
    """按 case_items 实况重算用例集生成条数。"""
    case_set.generated_count = (
        db.query(CaseItem).filter(CaseItem.case_set_id == case_set.id).count()
    )


def _get_cases_by_ids(db: Session, case_set: CaseSet, case_ids: list[str]) -> list[CaseItem]:
    """按 id 列表读取用例行；任一 id 不属于该用例集时抛出 VALIDATION。"""
    rows = (
        db.query(CaseItem)
        .filter(CaseItem.case_set_id == case_set.id, CaseItem.id.in_(case_ids))
        .all()
    )
    if len(rows) != len(set(case_ids)):
        raise AppError(ErrorCode.VALIDATION, "case_ids 必须全部属于该用例集")
    by_id = {row.id: row for row in rows}
    # 按请求顺序返回，保证映射/补全的处理顺序与前端勾选顺序一致
    return [by_id[case_id] for case_id in case_ids]


def _upsert_case(
    db: Session, case_set: CaseSet, case_in: CaseIn, case: CaseItem | None, sort_order: int
) -> CaseItem:
    """按用例 id 更新或插入单行；已有行上未提供的可空字段保留原值。"""
    provided = case_in.model_fields_set
    if case is None:
        case = CaseItem(
            id=case_in.id or uuid_str(),
            case_set_id=case_set.id,
            strategy=case_in.strategy,
            priority=case_in.priority,
            module=case_in.module,
            name=case_in.name,
            precondition=case_in.precondition or "",
            steps=case_in.steps or "",
            expected=case_in.expected or "",
            test_type=case_in.test_type or "",
            sort_order=sort_order,
        )
        db.add(case)
    else:
        case.strategy = case_in.strategy
        case.priority = case_in.priority
        case.module = case_in.module
        case.name = case_in.name
        if "precondition" in provided:
            case.precondition = case_in.precondition or ""
        if "steps" in provided:
            case.steps = case_in.steps or ""
        if "expected" in provided:
            case.expected = case_in.expected or ""
        if "test_type" in provided:
            case.test_type = case_in.test_type or ""
    extras = {k: v for k, v in (case_in.model_extra or {}).items() if k not in _RESERVED_EXTRA_KEYS}
    if extras:
        merged = dict(case.extras or {})
        merged.update(extras)
        case.extras = merged
    # name / expected 任一缺失即视为待补全，映射入库时进入目标集待补全行
    case.pending_complete = not (case.name or "").strip() or not (case.expected or "").strip()
    return case


def _normalize_strategy_weights(weights: dict[str, int] | None) -> dict[str, int]:
    """校验并归一化策略配比；缺省使用契约默认配比。"""
    if not weights:
        return dict(_DEFAULT_STRATEGY_WEIGHTS)
    unknown = set(weights) - set(_STRATEGY_NAMES)
    if unknown:
        raise AppError(
            ErrorCode.VALIDATION, f"strategy_weights 包含未知策略：{'、'.join(sorted(unknown))}"
        )
    for value in weights.values():
        if value < 0:
            raise AppError(ErrorCode.VALIDATION, "strategy_weights 配比必须为非负整数")
    if sum(weights.values()) <= 0:
        raise AppError(ErrorCode.VALIDATION, "strategy_weights 配比总和必须大于 0")
    return dict(weights)


def _read_source_doc_text(stored: StoredFile) -> str:
    """读取来源文档文本：xlsx 提取单元格文本，其余按 UTF-8 容错解码并截断。"""
    try:
        if (stored.kind or "").lower() == "xlsx":
            workbook = load_workbook(stored.storage_path, read_only=True, data_only=True)
            try:
                lines = []
                for sheet in workbook.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        line = " ".join(str(cell) for cell in row if cell is not None)
                        if line.strip():
                            lines.append(line)
            finally:
                workbook.close()
            return "\n".join(lines)[:_SOURCE_DOC_MAX_CHARS]
        return Path(stored.storage_path).read_bytes().decode("utf-8", errors="ignore")[
            :_SOURCE_DOC_MAX_CHARS
        ]
    except Exception as exc:
        raise AppError(
            ErrorCode.VALIDATION, "来源文档内容不可读，请改用 source_text 直接粘贴原文"
        ) from exc


def _build_ai_generate_prompts(
    body: CaseAiGenerateIn, weights: dict[str, int], source_sections: list[str]
) -> tuple[str, str]:
    """组装候选用例生成的中文 system / user prompt。"""
    ratio_desc = "、".join(f"{_STRATEGY_NAMES[key]} {value}%" for key, value in weights.items())
    system = (
        "你是资深测试设计专家，负责根据需求文档设计软件测试用例。"
        "每条用例必须包含 strategy（策略，取值限于 正向/反向/边界/等价类/状态迁移/场景）、"
        "priority（优先级，P0/P1/P2）、module（所属模块）、name（用例名称）、"
        "expected（预期结果）、precondition（前置条件）、"
        "test_type（测试类型，如 核心业务/异常处理/兼容性），可选 steps（操作步骤）。"
        "只输出一个 JSON 数组，不要输出任何解释文字或 markdown 代码围栏。"
    )
    sections = [f"请按以下策略配比生成不超过 {body.max_count} 条测试用例：{ratio_desc}。"]
    if body.complexity:
        sections.append(f"业务复杂度：{body.complexity}。")
    sections.extend(source_sections)
    return system, "\n\n".join(sections)


def _rebalance_by_strategy(
    items: list[dict], weights: dict[str, int], max_count: int
) -> list[dict]:
    """按策略配比对候选条数做软性校正：超出配比的截断，不足的保留。"""
    total_weight = sum(weights.values())
    quotas = {
        _STRATEGY_NAMES[key]: (max(1, round(max_count * value / total_weight)) if value > 0 else 0)
        for key, value in weights.items()
    }
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(str(item.get("strategy", "")), []).append(item)
    result: list[dict] = []
    for strategy, group in grouped.items():
        quota = quotas.get(strategy)
        # 未在配比中的策略（模型自由发挥）全量保留；配比内策略超出配额即截断
        result.extend(group if quota is None else group[:quota])
    return result[:max_count]


def _build_ai_fill_prompts(
    case_set: CaseSet, cases: list[CaseItem], body: CaseAiFillIn
) -> tuple[str, str]:
    """组装行级补全的中文 system / user prompt，要求模型仅补全缺失字段。"""
    columns = case_set.column_schema or []
    column_desc = "、".join(f"{col.get('key')}（{col.get('name')}）" for col in columns) or "无"
    fillable = body.fields or ["expected", "precondition", "test_type"]
    system = (
        "你是测试用例补全助手，负责补全测试用例中缺失的字段。"
        f"本次可补全字段：{'、'.join(fillable)}；用例集已声明的扩展列：{column_desc}。"
        "只输出一个 JSON 数组，每项必须包含原用例 id 与补全后的字段，"
        "不要输出任何解释文字或 markdown 代码围栏。"
    )
    rows_text = json.dumps([_case_to_item(case) for case in cases], ensure_ascii=False, indent=2)
    sections = [
        f"以下是待补全的用例行（JSON 数组）：\n{rows_text}",
        "要求：保留每行 id 与已有非空字段不变，仅补全缺失或为空字符串的字段；"
        "输出仍是 JSON 数组，行数与输入一致。",
    ]
    if body.fields:
        sections.append(f"本次仅补全以下字段：{'、'.join(body.fields)}。")
    if body.instruction:
        sections.append(f"补全侧重点：{body.instruction}")
    return system, "\n\n".join(sections)


def _filter_fill_items(items: list[dict], body: CaseAiFillIn) -> list[dict]:
    """过滤模型输出：仅保留请求内的用例 id；指定 fields 时剔除字段外 key。"""
    allowed_ids = set(body.case_ids)
    allowed_fields = set(body.fields) if body.fields else None
    result: list[dict] = []
    for item in items:
        item_id = item.get("id")
        if not item_id or item_id not in allowed_ids:
            continue
        if allowed_fields is not None:
            item = {k: v for k, v in item.items() if k == "id" or k in allowed_fields}
        result.append(item)
    return result


def _build_xlsx(case_set: CaseSet, cases: list[CaseItem]) -> bytes:
    """生成 Excel 工作簿字节流：固定列 + column_schema 声明的扩展列。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "用例集"
    extra_columns = [
        (col.get("key", ""), col.get("name") or col.get("key", ""))
        for col in (case_set.column_schema or [])
    ]
    sheet.append([title for _, title in _EXPORT_FIXED_COLUMNS] + [name for _, name in extra_columns])
    for case in cases:
        item = _case_to_item(case)
        row: list[Any] = []
        for field, _title in _EXPORT_FIXED_COLUMNS:
            value = item.get(field)
            if isinstance(value, bool):
                value = "是" if value else "否"
            row.append(value)
        row.extend((case.extras or {}).get(key) for key, _ in extra_columns)
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _xmind_topic(topic_id: str, title: str, timestamp: int, note: str = "", children: str = "") -> str:
    """拼接单个 XMind topic 节点 XML；标题与备注均做 XML 转义。"""
    parts = [f'<topic id="{topic_id}" timestamp="{timestamp}">', f"<title>{escape(title)}</title>"]
    if note:
        parts.append(f"<notes><plain>{escape(note)}</plain></notes>")
    if children:
        parts.append(f'<children><topics type="attached">{children}</topics></children>')
    parts.append("</topic>")
    return "".join(parts)


def _build_xmind(case_set: CaseSet, cases: list[CaseItem]) -> bytes:
    """生成 XMind 8 文件字节流（zip：content.xml + META-INF/manifest.xml）。

    结构：根节点=用例集名，二级节点按 module 分组，叶子=用例名（expected 写入备注）。
    """
    timestamp = int(time.time() * 1000)
    modules: dict[str, list[CaseItem]] = {}
    for case in cases:
        modules.setdefault(case.module or "未分组", []).append(case)
    modules_xml = "".join(
        _xmind_topic(
            uuid_str(),
            module,
            timestamp,
            children="".join(
                _xmind_topic(uuid_str(), case.name, timestamp, note=case.expected or "")
                for case in group
            ),
        )
        for module, group in modules.items()
    )
    content_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        '<xmap-content xmlns="urn:xmind:xmap:xmlns:content:2.0" '
        'xmlns:fo="http://www.w3.org/1999/XSL/Format" '
        'xmlns:svg="http://www.w3.org/2000/svg" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" version="2.0">'
        f'<sheet id="{uuid_str()}" timestamp="{timestamp}">'
        + _xmind_topic(uuid_str(), case_set.name, timestamp, children=modules_xml)
        + "</sheet></xmap-content>"
    )
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        '<manifest xmlns="urn:xmind:xmap:xmlns:manifest:1.0">'
        '<file-entry full-path="content.xml" media-type="text/xml"/>'
        "</manifest>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", content_xml)
        archive.writestr("META-INF/manifest.xml", manifest_xml)
    return buffer.getvalue()


@router.get("")
def list_case_sets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出全部用例集，按契约返回 {items, total} 包装。"""
    rows = db.query(CaseSet).order_by(CaseSet.created_at.desc()).all()
    return {"items": [CaseSetOut.model_validate(row) for row in rows], "total": len(rows)}


@router.post("", response_model=CaseSetOut, status_code=201)
def create_case_set(
    body: CaseSetCreate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建空用例集（status=generated，generated_count=0）；expires_at 留空由任务域写入。"""
    if body.folder_id:
        _assert_folder_exists(db, body.folder_id)
    case_set = CaseSet(
        name=body.name,
        folder_id=body.folder_id,
        column_schema=[col.model_dump() for col in body.column_schema or []],
        created_by=user.id,
    )
    db.add(case_set)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_set_create",
            target_type="case_set",
            target_id=case_set.id,
            detail={"name": case_set.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(case_set)
    return case_set


# 固定路径 /ai-generate 必须声明在 /{set_id} 之前，避免被路径参数吞掉
@router.post("/ai-generate")
def ai_generate_cases(
    body: CaseAiGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按 6 大策略配比生成候选用例；只返回未落库候选，不创建用例集。"""
    weights = _normalize_strategy_weights(body.strategy_weights)
    source_sections: list[str] = []
    if body.source_doc_id:
        stored = db.query(StoredFile).filter(StoredFile.id == body.source_doc_id).first()
        if not stored:
            raise AppError(ErrorCode.NOT_FOUND, "来源文档不存在")
        doc_text = _read_source_doc_text(stored)
        source_sections.append(f"来源文档《{stored.filename}》内容：\n{doc_text}")
    if body.source_text and body.source_text.strip():
        source_sections.append(f"需求原文：\n{body.source_text.strip()}")
    system, user_prompt = _build_ai_generate_prompts(body, weights, source_sections)
    text = call_agent_model(db, system, user_prompt, max_tokens=4096)
    items = parse_json_candidates(text)
    return {"items": _rebalance_by_strategy(items, weights, body.max_count)}


@router.get("/{set_id}", response_model=CaseSetDetailOut)
def get_case_set(
    set_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取用例集详情，含全部用例行（固定字段 + 扩展列平铺）。"""
    case_set = _get_case_set_or_404(db, set_id)
    detail = CaseSetDetailOut.model_validate(case_set)
    detail.cases = [_case_to_item(case) for case in _list_cases(db, case_set)]
    return detail


@router.put("/{set_id}", response_model=CaseSetOut)
def update_case_set(
    set_id: str,
    body: CaseSetUpdate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按提供的字段更新用例集；column_schema 整体替换，confirmed 集拒绝修改。"""
    case_set = _get_case_set_or_404(db, set_id)
    _assert_editable(case_set)
    values = body.model_dump(exclude_unset=True)
    if "folder_id" in values:
        folder_id = values.pop("folder_id")
        if folder_id is not None:
            _assert_folder_exists(db, folder_id)
        case_set.folder_id = folder_id
    if "column_schema" in values:
        case_set.column_schema = values.pop("column_schema")
    for field, value in values.items():
        setattr(case_set, field, value)
    # 用例集元信息变更写审计（与 dataset_update / folder_update 口径一致）
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_set_update",
            target_type="case_set",
            target_id=case_set.id,
            detail={"name": case_set.name, "fields": sorted(body.model_fields_set)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(case_set)
    return case_set


@router.put("/{set_id}/cases")
def save_cases(
    set_id: str,
    body: CasesPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按用例 id 批量 upsert 用例行与扩展列；id 缺省时服务端生成，保存后重算 generated_count。"""
    case_set = _get_case_set_or_404(db, set_id)
    _assert_editable(case_set)
    existing = {
        case.id: case
        for case in db.query(CaseItem).filter(CaseItem.case_set_id == case_set.id).all()
    }
    for index, case_in in enumerate(body.cases):
        target = existing.get(case_in.id) if case_in.id else None
        if case_in.id and target is None:
            # 显式 id 未命中时按插入处理；若 id 已被其他用例集占用则拒绝，避免跨集串行
            clash = db.query(CaseItem).filter(CaseItem.id == case_in.id).first()
            if clash:
                raise AppError(ErrorCode.VALIDATION, f"用例 {case_in.id} 不属于该用例集")
        _upsert_case(db, case_set, case_in, target, index)
    db.flush()
    _refresh_generated_count(db, case_set)
    db.commit()
    cases = _list_cases(db, case_set)
    return {"items": [_case_to_item(case) for case in cases], "total": len(cases)}


@router.post("/{set_id}/confirm", response_model=CaseSetOut)
def confirm_case_set(
    set_id: str,
    body: CaseConfirmIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """确认用例入库（ok=true）或废弃（ok=false），并联动关联 testcase 任务状态。

    edits / mapping_target / target_id 为契约预留字段，仅记入审计明细；
    实际映射入库走 POST /{set_id}/map。
    """
    case_set = _get_case_set_or_404(db, set_id)
    if case_set.status in {"confirmed", "cancelled"}:
        raise AppError(ErrorCode.VALIDATION, "用例集已终态，请勿重复操作")
    if body.ok:
        case_set.status = "confirmed"
        case_set.confirmed_count = case_set.generated_count
        task_status = "succeeded"
    else:
        case_set.status = "cancelled"
        task_status = "cancelled"
    # 仅当关联任务仍在等待用例确认时联动流转，其余状态由任务域自行负责
    if case_set.task_id:
        task = db.query(Task).filter(Task.id == case_set.task_id).first()
        if task and task.status == "awaiting_case_confirm":
            task.status = task_status
            task.finished_at = utcnow()
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_set_confirm",
            target_type="case_set",
            target_id=case_set.id,
            detail={
                "name": case_set.name,
                "ok": body.ok,
                "mapping_target": body.mapping_target,
                "target_id": body.target_id,
            },
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(case_set)
    return case_set


@router.post("/{set_id}/cancel", response_model=CaseSetOut)
def cancel_case_set(
    set_id: str,
    body: CaseCancelIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """废弃用例集；关联的 awaiting_case_confirm 任务同步置 cancelled。"""
    case_set = _get_case_set_or_404(db, set_id)
    if case_set.status in {"confirmed", "cancelled"}:
        raise AppError(ErrorCode.VALIDATION, "用例集已终态，请勿重复操作")
    case_set.status = "cancelled"
    if case_set.task_id:
        task = db.query(Task).filter(Task.id == case_set.task_id).first()
        if task and task.status == "awaiting_case_confirm":
            task.status = "cancelled"
            task.finished_at = utcnow()
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_set_cancel",
            target_type="case_set",
            target_id=case_set.id,
            detail={"name": case_set.name, "reason": body.reason},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(case_set)
    return case_set


@router.post("/{set_id}/map")
def map_cases(
    set_id: str,
    body: CaseMapIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量映射用例到目标基准数据集；黄金 QA 域（M3）尚未上线，统一返回 VALIDATION。"""
    case_set = _get_case_set_or_404(db, set_id)
    if body.target == "gold_qa":
        raise AppError(ErrorCode.VALIDATION, "知识库域尚未上线，暂不支持映射到黄金 QA")
    dataset = db.query(Dataset).filter(Dataset.id == body.target_id).first()
    if not dataset:
        raise AppError(ErrorCode.VALIDATION, "目标 ID 类型不匹配或不存在")
    cases = _get_cases_by_ids(db, case_set, body.case_ids)
    max_row_no = (
        db.query(func.max(DatasetRow.row_no)).filter(DatasetRow.dataset_id == dataset.id).scalar()
        or 0
    )
    pending_count = 0
    for offset, case in enumerate(cases, start=1):
        question = (case.name or "").strip()
        reference = (case.expected or "").strip()
        pending = not question or not reference
        if pending:
            pending_count += 1
        db.add(
            DatasetRow(
                dataset_id=dataset.id,
                row_no=max_row_no + offset,
                question=question,
                reference=reference,
                pending_complete=pending,
                # 仅待补全行回写 source_case_id，便于人工补全时回溯来源用例
                source_case_id=case.id if pending else None,
            )
        )
        case.mapped = True
        case.pending_complete = False
    db.flush()
    # 按 dataset_rows 实况重算目标集行数与待补全行数
    rows = db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset.id).all()
    dataset.row_count = len(rows)
    dataset.pending_complete_count = sum(1 for row in rows if row.pending_complete)
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_set_map",
            target_type="case_set",
            target_id=case_set.id,
            detail={
                "name": case_set.name,
                "target": body.target,
                "target_id": body.target_id,
                "case_count": len(cases),
                "pending_count": pending_count,
            },
            ip=_request_ip(request),
        )
    )
    db.commit()
    return {
        "ok": True,
        "mapped_count": len(cases),
        "pending_count": pending_count,
        "dataset_id": dataset.id,
    }


@router.post("/{set_id}/ai-fill")
def ai_fill_cases(
    set_id: str,
    body: CaseAiFillIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """行级 AI 补全：仅返回未落库候选值，前端确认后必须再走 PUT cases 保存。"""
    case_set = _get_case_set_or_404(db, set_id)
    _assert_editable(case_set)
    cases = _get_cases_by_ids(db, case_set, body.case_ids)
    system, user_prompt = _build_ai_fill_prompts(case_set, cases, body)
    text = call_agent_model(db, system, user_prompt, max_tokens=4096)
    items = parse_json_candidates(text)
    return {"items": _filter_fill_items(items, body)}


@router.get("/{set_id}/export")
def export_case_set(
    set_id: str,
    request: FastApiRequest,
    fmt: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出用例集为 xlsx 或 xmind 文件流；generated/confirmed 均可导出，fmt 必填。"""
    case_set = _get_case_set_or_404(db, set_id)
    cases = _list_cases(db, case_set)
    if fmt == "xlsx":
        content, media_type, suffix = _build_xlsx(case_set, cases), _XLSX_MEDIA_TYPE, ".xlsx"
    elif fmt == "xmind":
        content, media_type, suffix = _build_xmind(case_set, cases), _XMIND_MEDIA_TYPE, ".xmind"
    else:
        raise AppError(ErrorCode.VALIDATION, "fmt 仅支持 xlsx 或 xmind")
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_set_export",
            target_type="case_set",
            target_id=case_set.id,
            detail={"name": case_set.name, "fmt": fmt, "case_count": len(cases)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    # 中文文件名按 RFC 5987 编码，避免 Content-Disposition 乱码
    filename = quote(f"{case_set.name}{suffix}")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@folders_router.get("")
def list_case_folders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按排序号返回全部用例目录节点，前端自行组装树。"""
    rows = (
        db.query(CaseFolder)
        .order_by(CaseFolder.sort_order.asc(), CaseFolder.created_at.asc())
        .all()
    )
    return {"items": [FolderOut.model_validate(row) for row in rows], "total": len(rows)}


@folders_router.post("", response_model=FolderOut, status_code=201)
def create_case_folder(
    body: FolderIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建用例目录节点；parent_id 缺省表示根目录。"""
    if not body.name:
        raise AppError(ErrorCode.VALIDATION, "目录名称不能为空")
    if body.parent_id:
        _assert_folder_exists(db, body.parent_id)
    folder = CaseFolder(
        name=body.name,
        parent_id=body.parent_id,
        sort_order=body.sort_order or 0,
    )
    db.add(folder)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_folder_create",
            target_type="case_folder",
            target_id=folder.id,
            detail={"name": folder.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(folder)
    return folder


@folders_router.put("/{folder_id}", response_model=FolderOut)
def update_case_folder(
    folder_id: str,
    body: FolderIn,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按提供的字段更新用例目录；移动时校验父目录存在且不构成环。"""
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
                node = db.query(CaseFolder).filter(CaseFolder.id == current).first()
                current = node.parent_id if node else None
        folder.parent_id = parent_id
    for field, value in values.items():
        if value is not None:
            setattr(folder, field, value)
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_folder_update",
            target_type="case_folder",
            target_id=folder.id,
            detail={"name": folder.name, "fields": sorted(body.model_fields_set)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(folder)
    return folder


@folders_router.delete("/{folder_id}")
def delete_case_folder(
    folder_id: str,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除空目录；仍含用例集或子目录时返回 VALIDATION。"""
    folder = _get_folder_or_404(db, folder_id)
    if db.query(CaseFolder).filter(CaseFolder.parent_id == folder.id).first():
        raise AppError(ErrorCode.VALIDATION, "目录下仍有子目录，无法删除")
    if db.query(CaseSet).filter(CaseSet.folder_id == folder.id).first():
        raise AppError(ErrorCode.VALIDATION, "目录下仍有用例集，无法删除")
    db.delete(folder)
    db.add(
        AuditLog(
            user_id=user.id,
            action="case_folder_delete",
            target_type="case_folder",
            target_id=folder_id,
            detail={"name": folder.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    return {"ok": True}
