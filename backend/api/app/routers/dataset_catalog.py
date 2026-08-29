"""受控基准目录与独立导入作业 API（M3）。

目录只保存已审核的固定 release manifest；浏览器永不提交下载凭据、任意 URL
或解析脚本。导入作业与评测 Task 完全分离，Worker 仅领取已冻结的 manifest。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request
from shared.dataset_import import SUPPORTED_DATASET_IMPORT_PARSERS
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import (
    AuditLog,
    Dataset,
    DatasetCatalogEntry,
    DatasetCatalogRelease,
    DatasetCatalogReview,
    DatasetFolder,
    DatasetImport,
    DatasetImportRow,
    DatasetVersion,
    DatasetVersionRow,
    User,
    utcnow,
    uuid_str,
)
from ..schemas import (
    CatalogEntryIn,
    CatalogReleaseIn,
    DatasetImportCreate,
    PublishImportIn,
    ResolveBlockIn,
    ReviewNoteIn,
)

router = APIRouter(prefix="/api", tags=["dataset-catalog"])
_OPEN_IMPORT_STATUSES = {"queued", "downloading", "validating", "parsing", "review_ready"}


def _request_ip(request: Request) -> str | None:
    """提取审计日志的请求来源 IP。"""
    return request.client.host if request.client else None


def _canonical_hash(value: dict[str, Any]) -> str:
    """为 manifest、筛选条件和幂等请求生成稳定 SHA-256。"""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_https_url(value: str, *, field_name: str) -> str:
    """目录登记仅允许 HTTPS URL，拒绝凭据和非网络协议。"""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise AppError(ErrorCode.VALIDATION, f"{field_name} 必须是无凭据的 HTTPS 地址")
    return parsed.hostname.lower()


def _review(
    db: Session,
    *,
    entry: DatasetCatalogEntry | None,
    release: DatasetCatalogRelease | None,
    actor_id: str,
    action: str,
    previous_status: str | None,
    next_status: str,
    note: str | None,
) -> None:
    """追加目录状态迁移审计，避免用可变字段覆盖复核历史。"""
    db.add(
        DatasetCatalogReview(
            catalog_entry_id=entry.id if entry else None,
            release_id=release.id if release else None,
            actor_id=actor_id,
            action=action,
            previous_status=previous_status,
            next_status=next_status,
            manifest_hash=release.manifest_hash if release else None,
            note=note,
        )
    )


def _audit(
    db: Session,
    request: Request,
    user: User,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, Any],
) -> None:
    """写入不含凭据、上游正文或制品内容的通用审计记录。"""
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip=_request_ip(request),
        )
    )


def _entry_or_404(db: Session, entry_id: str) -> DatasetCatalogEntry:
    """读取目录来源，不存在时使用统一 NOT_FOUND 错误。"""
    entry = db.query(DatasetCatalogEntry).filter(DatasetCatalogEntry.id == entry_id).first()
    if not entry:
        raise AppError(ErrorCode.NOT_FOUND, "目录来源不存在")
    return entry


def _release_or_404(db: Session, release_id: str) -> DatasetCatalogRelease:
    """读取固定 release，不存在时使用统一 NOT_FOUND 错误。"""
    release = db.query(DatasetCatalogRelease).filter(DatasetCatalogRelease.id == release_id).first()
    if not release:
        raise AppError(ErrorCode.NOT_FOUND, "目录 release 不存在")
    return release


def _entry_out(entry: DatasetCatalogEntry) -> dict[str, Any]:
    """返回来源草稿安全字段，不返回任何下载密钥或授权正文。"""
    return {
        "id": entry.id,
        "name": entry.name,
        "upstream_owner": entry.upstream_owner,
        "official_project_url": entry.official_project_url,
        "allowed_domains": entry.allowed_domains or [],
        "purpose": entry.purpose,
        "status": entry.status,
        "submitter_id": entry.submitted_by,
        "created_at": entry.created_at,
    }


def _release_out(release: DatasetCatalogRelease) -> dict[str, Any]:
    """返回 release 元数据；manifest 保持可审计但不含凭据字段。"""
    metadata = release.manifest.get("metadata", {}) if isinstance(release.manifest, dict) else {}
    return {
        "id": release.id,
        "catalog_entry_id": release.catalog_entry_id,
        "display_version": release.display_version,
        "source_revision": release.source_revision,
        "manifest_hash": release.manifest_hash,
        "license": release.license or {},
        "license_status": (release.license or {}).get("status"),
        "allowed_splits": release.allowed_splits or [],
        "filter_schema": release.filter_schema or {},
        "parser_id": release.parser_id,
        "parser_version": release.parser_version,
        "task_family": release.task_family,
        "support_status": release.support_status,
        "risk_labels": release.risk_labels or [],
        "test_availability": metadata.get("test_availability"),
        "estimated_rows": metadata.get("estimated_rows"),
        "status": release.status,
        "submitter_id": release.submitted_by,
        "approved_by": release.approved_by,
    }


def _catalog_domains(raw_domains: list[str]) -> list[str]:
    """规范化来源允许域名，防止同一主机因大小写重复进入 manifest。"""
    return sorted(
        {
            _validate_https_url(f"https://{item.strip()}", field_name="allowed_domains")
            for item in raw_domains
        }
    )


def _validate_release_payload(entry: DatasetCatalogEntry, body: CatalogReleaseIn) -> str:
    """校验 release 草稿的静态边界并返回固定 manifest 哈希。"""
    if body.source_revision.strip().lower() in {"main", "master", "latest"}:
        raise AppError(ErrorCode.VALIDATION, "source_revision 不允许使用浮动分支")
    artifacts = body.manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AppError(ErrorCode.VALIDATION, "manifest 必须包含 artifacts 制品清单")
    allowed = set(entry.allowed_domains or [])
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("url"), str):
            raise AppError(ErrorCode.VALIDATION, "制品必须包含 HTTPS url")
        host = _validate_https_url(artifact["url"], field_name="artifact.url")
        digest = artifact.get("sha256")
        if host not in allowed or not isinstance(digest, str) or len(digest) != 64:
            raise AppError(ErrorCode.VALIDATION, "制品域名或 SHA-256 不符合来源 manifest")
    if body.license.get("status") not in {"allowed", "review_required", "blocked"}:
        raise AppError(
            ErrorCode.VALIDATION, "license.status 必须明确为 allowed、review_required 或 blocked"
        )
    if body.filter_schema.get("version") != 1 or not isinstance(
        body.filter_schema.get("fields"), dict
    ):
        raise AppError(ErrorCode.VALIDATION, "filter_schema 必须提供 version=1 和 fields")
    if body.support_status == "supported" and body.parser_id not in SUPPORTED_DATASET_IMPORT_PARSERS:
        raise AppError(ErrorCode.VALIDATION, "标记为 supported 的 release 必须使用已注册解析器")
    return _canonical_hash(body.manifest)


def _validate_publish_rows(rows: list[DatasetImportRow]) -> None:
    """发布前校验必填字段、冻结 split 与重复样本，防止无效 staging 进入正式版本。"""
    invalid_rows: list[str] = []
    seen: dict[str, tuple[int, str]] = {}
    for row in rows:
        question = row.question.strip()
        reference = row.reference.strip()
        source_split = (row.provenance or {}).get("split")
        if not question or not reference:
            invalid_rows.append(f"第 {row.row_no} 行缺少题目或参考答案")
            continue
        if not isinstance(source_split, str) or not source_split.strip():
            invalid_rows.append(f"第 {row.row_no} 行缺少冻结 split")
            continue
        content_key = _canonical_hash({"question": question, "reference": reference})
        previous = seen.get(content_key)
        if previous is None:
            seen[content_key] = (row.row_no, source_split)
        elif previous[1] == source_split:
            invalid_rows.append(f"第 {row.row_no} 行与第 {previous[0]} 行重复")
        else:
            invalid_rows.append(
                f"第 {row.row_no} 行与第 {previous[0]} 行跨 split 重复"
            )
    if invalid_rows:
        summary = "；".join(invalid_rows[:8])
        raise AppError(ErrorCode.VALIDATION, f"选择的 staging 行未通过发布校验：{summary}")


@router.post("/dataset-catalog-entries", status_code=201)
def create_catalog_entry(
    body: CatalogEntryIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建来源草稿；release 通过双人复核前不会进入公开导入目录。"""
    _validate_https_url(body.official_project_url, field_name="official_project_url")
    domains = _catalog_domains(body.allowed_domains)
    entry = DatasetCatalogEntry(
        name=body.name.strip(),
        upstream_owner=body.upstream_owner.strip(),
        official_project_url=body.official_project_url,
        allowed_domains=domains,
        purpose=body.purpose,
        evidence_refs=body.evidence_refs,
        submitted_by=user.id,
    )
    db.add(entry)
    db.flush()
    _review(
        db,
        entry=entry,
        release=None,
        actor_id=user.id,
        action="create",
        previous_status=None,
        next_status="draft",
        note=None,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_entry_create",
        "dataset_catalog_entry",
        entry.id,
        {"status": "draft"},
    )
    db.commit()
    return _entry_out(entry)


@router.put("/dataset-catalog-entries/{entry_id}")
def update_catalog_entry(
    entry_id: str,
    body: CatalogEntryIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """仅允许提报成员在 draft 阶段修订来源身份，避免破坏已审核 release。"""
    entry = _entry_or_404(db, entry_id)
    if entry.submitted_by != user.id or entry.status != "draft":
        raise AppError(ErrorCode.VALIDATION, "仅提报成员可修改 draft 来源")
    _validate_https_url(body.official_project_url, field_name="official_project_url")
    entry.name = body.name.strip()
    entry.upstream_owner = body.upstream_owner.strip()
    entry.official_project_url = body.official_project_url
    entry.allowed_domains = _catalog_domains(body.allowed_domains)
    entry.purpose = body.purpose
    entry.evidence_refs = body.evidence_refs
    _review(
        db,
        entry=entry,
        release=None,
        actor_id=user.id,
        action="update",
        previous_status="draft",
        next_status="draft",
        note=None,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_entry_update",
        "dataset_catalog_entry",
        entry.id,
        {"status": "draft"},
    )
    db.commit()
    return _entry_out(entry)


@router.post("/dataset-catalog-entries/{entry_id}/releases", status_code=201)
def create_catalog_release(
    entry_id: str,
    body: CatalogReleaseIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """登记带 SHA-256 的固定 release 草稿，禁止浮动 revision 和任意制品地址。"""
    entry = _entry_or_404(db, entry_id)
    if entry.status == "archived":
        raise AppError(ErrorCode.VALIDATION, "已归档来源不能新增 release")
    manifest_hash = _validate_release_payload(entry, body)
    release = DatasetCatalogRelease(
        catalog_entry_id=entry.id,
        display_version=body.display_version,
        source_revision=body.source_revision,
        manifest=body.manifest,
        manifest_hash=manifest_hash,
        license=body.license,
        allowed_splits=sorted(set(body.allowed_splits)),
        filter_schema=body.filter_schema,
        parser_id=body.parser_id,
        parser_version=body.parser_version,
        task_family=body.task_family,
        support_status=body.support_status,
        risk_labels=body.risk_labels,
        submitted_by=user.id,
    )
    db.add(release)
    db.flush()
    _review(
        db,
        entry=entry,
        release=release,
        actor_id=user.id,
        action="create",
        previous_status=None,
        next_status="draft",
        note=None,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_release_create",
        "dataset_catalog_release",
        release.id,
        {"manifest_hash": manifest_hash},
    )
    db.commit()
    return _release_out(release)


@router.put("/dataset-catalog-releases/{release_id}")
def update_catalog_release(
    release_id: str,
    body: CatalogReleaseIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """草稿修订会重算 manifest 哈希；提交审核后必须新建 release。"""
    release = _release_or_404(db, release_id)
    if release.submitted_by != user.id or release.status != "draft":
        raise AppError(ErrorCode.VALIDATION, "仅提报成员可修改 draft release")
    entry = _entry_or_404(db, release.catalog_entry_id)
    manifest_hash = _validate_release_payload(entry, body)
    release.display_version = body.display_version
    release.source_revision = body.source_revision
    release.manifest = body.manifest
    release.manifest_hash = manifest_hash
    release.license = body.license
    release.allowed_splits = sorted(set(body.allowed_splits))
    release.filter_schema = body.filter_schema
    release.parser_id = body.parser_id
    release.parser_version = body.parser_version
    release.task_family = body.task_family
    release.support_status = body.support_status
    release.risk_labels = body.risk_labels
    _review(
        db,
        entry=entry,
        release=release,
        actor_id=user.id,
        action="update",
        previous_status="draft",
        next_status="draft",
        note=None,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_release_update",
        "dataset_catalog_release",
        release.id,
        {"manifest_hash": manifest_hash},
    )
    db.commit()
    return _release_out(release)


@router.post("/dataset-catalog-releases/{release_id}/submit-review")
def submit_release_review(
    release_id: str,
    body: ReviewNoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将自己的草稿提交复核，提交后不允许原地修改 manifest。"""
    release = _release_or_404(db, release_id)
    if release.submitted_by != user.id or release.status != "draft":
        raise AppError(ErrorCode.VALIDATION, "仅提报成员可提交处于 draft 的 release")
    entry = _entry_or_404(db, release.catalog_entry_id)
    release.status = "reviewing"
    _review(
        db,
        entry=entry,
        release=release,
        actor_id=user.id,
        action="submit_review",
        previous_status="draft",
        next_status="reviewing",
        note=body.note,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_release_submit_review",
        "dataset_catalog_release",
        release.id,
        {},
    )
    db.commit()
    return _release_out(release)


@router.post("/dataset-catalog-releases/{release_id}/approve")
def approve_release(
    release_id: str,
    body: ReviewNoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """非提报成员复核 release；许可证未允许时不得批准为可导入。"""
    release = _release_or_404(db, release_id)
    if release.status != "reviewing" or release.submitted_by == user.id:
        raise AppError(ErrorCode.VALIDATION, "release 必须由非提报成员在 reviewing 状态批准")
    if (release.license or {}).get("status") != "allowed" or release.support_status != "supported":
        raise AppError(ErrorCode.VALIDATION, "许可证或任务族尚未满足可导入条件")
    entry = _entry_or_404(db, release.catalog_entry_id)
    release.status = "approved"
    release.approved_by = user.id
    release.approved_at = utcnow()
    entry.status = "active"
    _review(
        db,
        entry=entry,
        release=release,
        actor_id=user.id,
        action="approve",
        previous_status="reviewing",
        next_status="approved",
        note=body.note,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_release_approve",
        "dataset_catalog_release",
        release.id,
        {"manifest_hash": release.manifest_hash},
    )
    db.commit()
    return _release_out(release)


@router.post("/dataset-catalog-releases/{release_id}/block")
def block_release(
    release_id: str,
    body: ReviewNoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """任一成员可紧急封禁 release，立即阻止新导入并保留复核审计。"""
    release = _release_or_404(db, release_id)
    if release.status not in {"approved", "reviewing"}:
        raise AppError(ErrorCode.VALIDATION, "当前 release 不可封禁")
    entry = _entry_or_404(db, release.catalog_entry_id)
    previous = release.status
    release.status = "blocked"
    _review(
        db,
        entry=entry,
        release=release,
        actor_id=user.id,
        action="block",
        previous_status=previous,
        next_status="blocked",
        note=body.note,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_release_block",
        "dataset_catalog_release",
        release.id,
        {},
    )
    db.commit()
    return _release_out(release)


@router.post("/dataset-catalog-releases/{release_id}/resolve-block")
def resolve_release_block(
    release_id: str,
    body: ResolveBlockIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """封禁解除必须由不同成员复核；恢复时再次执行许可证与能力门禁。"""
    release = _release_or_404(db, release_id)
    if release.status != "blocked":
        raise AppError(ErrorCode.VALIDATION, "仅 blocked release 可以处理封禁复核")
    latest_block = (
        db.query(DatasetCatalogReview)
        .filter(
            DatasetCatalogReview.release_id == release.id, DatasetCatalogReview.action == "block"
        )
        .order_by(DatasetCatalogReview.created_at.desc())
        .first()
    )
    if not latest_block or user.id in {release.submitted_by, latest_block.actor_id}:
        raise AppError(ErrorCode.VALIDATION, "封禁复核必须由不同于提报和封禁成员的成员完成")
    entry = _entry_or_404(db, release.catalog_entry_id)
    if body.decision == "approved":
        if (release.license or {}).get(
            "status"
        ) != "allowed" or release.support_status != "supported":
            raise AppError(ErrorCode.VALIDATION, "许可证或任务族尚未满足可导入条件")
        release.status = "approved"
        release.approved_by = user.id
        release.approved_at = utcnow()
        entry.status = "active"
    _review(
        db,
        entry=entry,
        release=release,
        actor_id=user.id,
        action="resolve_block",
        previous_status="blocked",
        next_status=body.decision,
        note=body.note,
    )
    _audit(
        db,
        request,
        user,
        "dataset_catalog_release_resolve_block",
        "dataset_catalog_release",
        release.id,
        {"decision": body.decision},
    )
    db.commit()
    return _release_out(release)


@router.get("/dataset-catalog")
def list_catalog(
    scenario: str | None = Query(default=None),
    task_family: str | None = Query(default=None),
    language: str | None = Query(default=None),
    license_status: str | None = Query(default=None),
    test_availability: str | None = Query(default=None),
    support_status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询本地已批准目录；此接口绝不实时请求第三方平台。"""
    _ = user
    query = (
        db.query(DatasetCatalogRelease, DatasetCatalogEntry)
        .join(DatasetCatalogEntry, DatasetCatalogEntry.id == DatasetCatalogRelease.catalog_entry_id)
        .filter(DatasetCatalogEntry.status == "active", DatasetCatalogRelease.status == "approved")
    )
    if task_family:
        query = query.filter(DatasetCatalogRelease.task_family == task_family)
    if support_status:
        query = query.filter(DatasetCatalogRelease.support_status == support_status)
    if q:
        query = query.filter(DatasetCatalogEntry.name.ilike(f"%{q.strip()}%"))
    items: dict[str, dict[str, Any]] = {}
    for release, entry in query.order_by(DatasetCatalogEntry.name.asc()).all():
        metadata = (
            release.manifest.get("metadata", {}) if isinstance(release.manifest, dict) else {}
        )
        if scenario and scenario not in metadata.get("scenarios", []):
            continue
        if language and language not in metadata.get("language", []):
            continue
        if license_status and (release.license or {}).get("status") != license_status:
            continue
        if test_availability and metadata.get("test_availability") != test_availability:
            continue
        item = items.setdefault(
            entry.id,
            {
                "id": entry.id,
                "name": entry.name,
                "scenarios": metadata.get("scenarios", []),
                "task_family": release.task_family,
                "language": metadata.get("language", []),
                "license": release.license,
                "license_status": (release.license or {}).get("status"),
                "test_availability": metadata.get("test_availability"),
                "risk_labels": release.risk_labels or [],
                "releases": [],
            },
        )
        item["releases"].append(_release_out(release))
    return {"items": list(items.values()), "total": len(items)}


@router.post("/dataset-imports", status_code=202)
def create_import(
    body: DatasetImportCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按固定 release 创建幂等导入作业，绝不接收浏览器给出的下载地址。"""
    release = _release_or_404(db, body.release_id)
    entry = _entry_or_404(db, body.catalog_entry_id)
    if (
        release.catalog_entry_id != entry.id
        or entry.status != "active"
        or release.status != "approved"
    ):
        raise AppError(ErrorCode.VALIDATION, "目录来源或 release 尚未获准导入")
    if set(body.splits) - set(release.allowed_splits or []):
        raise AppError(ErrorCode.VALIDATION, "选择了 release 未允许的 split")
    schema = release.filter_schema or {}
    if body.filter_schema_version != schema.get("version") or set(body.filters) - set(
        schema.get("fields") or {}
    ):
        raise AppError(ErrorCode.VALIDATION, "筛选条件与 release filter_schema 不匹配")
    if body.target_dataset_id:
        dataset = (
            db.query(Dataset).filter(Dataset.id == body.target_dataset_id).with_for_update().first()
        )
        if not dataset:
            raise AppError(ErrorCode.NOT_FOUND, "目标数据集不存在")
        if body.target_name and body.target_name != dataset.name:
            raise AppError(ErrorCode.VALIDATION, "target_name 与 target_dataset_id 不一致")
    else:
        if body.folder_id and not db.query(DatasetFolder).filter(DatasetFolder.id == body.folder_id).first():
            raise AppError(ErrorCode.VALIDATION, "目标目录不存在")
        dataset = Dataset(
            name=body.target_name or "未命名导入数据集",
            folder_id=body.folder_id,
            created_by=user.id,
        )
        db.add(dataset)
        db.flush()
    if (
        db.query(DatasetImport)
        .filter(
            DatasetImport.dataset_id == dataset.id, DatasetImport.status.in_(_OPEN_IMPORT_STATUSES)
        )
        .first()
    ):
        raise AppError(ErrorCode.CONCURRENCY, "目标数据集已有未完成导入作业")
    fingerprint_payload = {
        "manifest_hash": release.manifest_hash,
        "splits": sorted(body.splits),
        "filters": body.filters,
        "parser_version": release.parser_version,
        "dataset_id": dataset.id,
    }
    fingerprint = _canonical_hash(fingerprint_payload)
    reused = (
        db.query(DatasetImport).filter(DatasetImport.request_fingerprint == fingerprint).first()
    )
    if reused:
        return {
            "id": reused.id,
            "dataset_id": reused.dataset_id,
            "status": reused.status,
            "stage": reused.stage,
            "attempt": reused.attempt,
            "manifest_hash": reused.manifest_hash,
            "reused": True,
            "created_at": reused.created_at,
        }
    manifest = {
        "release_id": release.id,
        "release_manifest_hash": release.manifest_hash,
        "release_manifest": release.manifest,
        # 导入领取后仍使用这份来源快照，目录后续编辑不会改变已提报作业的下载边界。
        "catalog_entry": {
            "id": entry.id,
            "official_project_url": entry.official_project_url,
            "allowed_domains": sorted(entry.allowed_domains or []),
        },
        "parser_id": release.parser_id,
        "parser_version": release.parser_version,
        "splits": sorted(body.splits),
        "filters": body.filters,
    }
    job = DatasetImport(
        dataset_id=dataset.id,
        catalog_release_id=release.id,
        request_fingerprint=fingerprint,
        manifest=manifest,
        manifest_hash=_canonical_hash(manifest),
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    _audit(
        db,
        request,
        user,
        "dataset_import_create",
        "dataset_import",
        job.id,
        {"dataset_id": dataset.id, "manifest_hash": job.manifest_hash},
    )
    db.commit()
    return {
        "id": job.id,
        "dataset_id": dataset.id,
        "status": job.status,
        "stage": job.stage,
        "attempt": job.attempt,
        "manifest_hash": job.manifest_hash,
        "reused": False,
        "created_at": job.created_at,
    }


@router.get("/dataset-imports/{import_id}")
def get_import(
    import_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """轮询独立导入作业；错误仅返回归一错误码和安全摘要。"""
    _ = user
    job = db.query(DatasetImport).filter(DatasetImport.id == import_id).first()
    if not job:
        raise AppError(ErrorCode.NOT_FOUND, "导入作业不存在")
    return {
        "id": job.id,
        "dataset_id": job.dataset_id,
        "status": job.status,
        "stage": job.stage,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "manifest_hash": job.manifest_hash,
        "staging_revision": job.staging_revision
        if job.status in {"review_ready", "published"}
        else None,
        "summary": job.summary or {},
        "error": job.error or None,
        "creator_id": job.created_by,
        "reviewer_id": job.reviewed_by,
    }


@router.post("/dataset-imports/{import_id}/retry", status_code=202)
def retry_import(
    import_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """仅允许对可恢复的上游/超时失败重新排队，保持原 manifest 与指纹不变。"""
    job = db.query(DatasetImport).filter(DatasetImport.id == import_id).with_for_update().first()
    if not job:
        raise AppError(ErrorCode.NOT_FOUND, "导入作业不存在")
    error_code = (job.error or {}).get("code")
    if job.status != "failed" or error_code not in {"UPSTREAM", "TIMEOUT"}:
        raise AppError(ErrorCode.VALIDATION, "仅 UPSTREAM 或 TIMEOUT 失败的作业可以重试")
    if job.attempt >= job.max_attempts:
        raise AppError(ErrorCode.VALIDATION, "作业已达到最大尝试次数，需新建导入")
    job.status = "queued"
    job.stage = "queued"
    job.lease_token = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.error = {}
    _audit(
        db,
        request,
        user,
        "dataset_import_retry",
        "dataset_import",
        job.id,
        {"attempt": job.attempt},
    )
    db.commit()
    return {"id": job.id, "status": job.status, "stage": job.stage, "attempt": job.attempt}


@router.post("/dataset-imports/{import_id}/reject")
def reject_import(
    import_id: str,
    body: ReviewNoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """非提报成员可拒绝 staging；拒绝不会修改任何已发布数据集版本。"""
    job = db.query(DatasetImport).filter(DatasetImport.id == import_id).with_for_update().first()
    if not job:
        raise AppError(ErrorCode.NOT_FOUND, "导入作业不存在")
    if job.status != "review_ready" or job.created_by == user.id:
        raise AppError(ErrorCode.VALIDATION, "仅非提报成员可拒绝 review_ready 导入")
    job.status = "rejected"
    job.stage = "rejected"
    job.reviewed_by = user.id
    job.summary = {**(job.summary or {}), "review_note": body.note}
    _audit(
        db, request, user, "dataset_import_reject", "dataset_import", job.id, {"note": body.note}
    )
    db.commit()
    return {"id": job.id, "status": job.status, "stage": job.stage}


@router.post("/datasets/{dataset_id}/publish-import")
def publish_import(
    dataset_id: str,
    body: PublishImportIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """以 import/revision/稳定行 ID 三重门禁原子发布不可变数据集版本。"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).with_for_update().first()
    job = (
        db.query(DatasetImport).filter(DatasetImport.id == body.import_id).with_for_update().first()
    )
    if not dataset or not job or job.dataset_id != dataset_id:
        raise AppError(ErrorCode.NOT_FOUND, "目标数据集或导入作业不存在")
    if job.created_by == user.id:
        raise AppError(ErrorCode.VALIDATION, "提报成员不能发布自己的导入")
    if job.status != "review_ready" or job.staging_revision != body.expected_staging_revision:
        raise AppError(ErrorCode.CONCURRENCY, "staging 已变化、未就绪或已发布，请刷新后重试")
    rows = (
        db.query(DatasetImportRow)
        .filter(
            DatasetImportRow.import_id == job.id,
            DatasetImportRow.id.in_(body.accepted_row_ids),
            DatasetImportRow.row_status == "staging",
        )
        .order_by(DatasetImportRow.row_no)
        .all()
    )
    if len(rows) != len(set(body.accepted_row_ids)):
        raise AppError(ErrorCode.VALIDATION, "存在无效、重复或已拒绝的 staging 行")
    _validate_publish_rows(rows)
    content_hash = _canonical_hash(
        {"manifest_hash": job.manifest_hash, "rows": [row.content_sha256 for row in rows]}
    )
    version_no = (
        db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).count()
    ) + 1
    version = DatasetVersion(
        id=uuid_str(),
        dataset_id=dataset.id,
        import_id=job.id,
        version_no=version_no,
        manifest=job.manifest,
        content_sha256=content_hash,
        scorer_version="m3-initial",
        published_by=user.id,
    )
    db.add(version)
    db.flush()
    for row in rows:
        db.add(
            DatasetVersionRow(
                dataset_version_id=version.id,
                source_import_row_id=row.id,
                row_no=row.row_no,
                question=row.question,
                reference=row.reference,
                context=row.context,
                extras=row.extras or {},
                provenance=row.provenance or {},
                content_sha256=row.content_sha256,
            )
        )
    dataset.active_version_id = version.id
    dataset.status = "active"
    dataset.row_count = len(rows)
    dataset.pending_complete_count = sum(
        1 for row in rows if not row.question.strip() or not row.reference.strip()
    )
    job.status = "published"
    job.stage = "published"
    job.reviewed_by = user.id
    job.summary = {**(job.summary or {}), "published_rows": len(rows), "version_id": version.id}
    _audit(
        db,
        request,
        user,
        "dataset_import_publish",
        "dataset_import",
        job.id,
        {"version_id": version.id, "staging_revision": job.staging_revision, "note": body.note},
    )
    db.commit()
    return {
        "id": version.id,
        "dataset_id": dataset.id,
        "version_no": version.version_no,
        "status": "active",
        "import_id": job.id,
    }
