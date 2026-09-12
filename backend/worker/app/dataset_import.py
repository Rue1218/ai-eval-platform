"""基准数据集受控导入 Worker（M3）。

导入不复用 ``Task`` 队列：每次领取均写入独立租约和尝试记录；来源制品只能
来自 API 已冻结的 release manifest。当前只支持受控 JSONL/CSV 问答解析器，
其它 parser 会显式失败，绝不执行目录或浏览器提交的任意代码。
"""

from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import secrets
import socket
from datetime import timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from shared.dataset_import import SUPPORTED_DATASET_IMPORT_PARSERS
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    DatasetImport,
    DatasetImportAttempt,
    DatasetImportRow,
    DatasetSourceArtifact,
    Setting,
    utcnow,
)

# 并发与单制品大小均为保守默认；设置表只控制领取并发，不放宽安全边界。
DEFAULT_MAX_RUNNING_DATASET_IMPORTS = 1
IMPORT_LEASE_SECONDS = 15 * 60
IMPORT_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
IMPORT_MAX_ROWS = 20_000
# 兼容已有测试与调用方；注册表唯一事实源在 backend/shared/dataset_import.py。
SUPPORTED_PARSERS = SUPPORTED_DATASET_IMPORT_PARSERS
IN_PROGRESS_STATUSES = {"downloading", "validating", "parsing"}


class ImportFailure(Exception):
    """受控导入的安全失败：仅携带可存储的统一错误码和中文摘要。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _max_running_dataset_imports(db: Session) -> int:
    """读取独立导入并发闸门；异常配置回退到 1，避免抢占评测资源。"""
    row = db.query(Setting).filter(Setting.key == "max_running_dataset_imports").first()
    value = row.value if row else None
    if isinstance(value, bool):
        return DEFAULT_MAX_RUNNING_DATASET_IMPORTS
    if isinstance(value, int | float) and value >= 1:
        return int(value)
    return DEFAULT_MAX_RUNNING_DATASET_IMPORTS


def _finish_attempt(
    db: Session,
    job: DatasetImport,
    *,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> None:
    """结束当前租约的尝试记录；记录不保存上游正文、URL 或数据样本。"""
    if not job.lease_token:
        return
    attempt = (
        db.query(DatasetImportAttempt)
        .filter(
            DatasetImportAttempt.import_id == job.id,
            DatasetImportAttempt.lease_token == job.lease_token,
        )
        .first()
    )
    if attempt:
        attempt.stage = job.stage
        attempt.error_code = error_code
        attempt.error_summary = error_summary
        attempt.finished_at = utcnow()


def recover_expired_dataset_import_leases(db: Session) -> int:
    """回收过期租约：未超过尝试上限重新排队，超过上限以 TIMEOUT 失败收束。"""
    now = utcnow()
    jobs = (
        db.query(DatasetImport)
        .filter(
            DatasetImport.status.in_(IN_PROGRESS_STATUSES),
            DatasetImport.lease_expires_at.isnot(None),
            DatasetImport.lease_expires_at < now,
        )
        .with_for_update(skip_locked=True)
        .all()
    )
    for job in jobs:
        if job.attempt >= job.max_attempts:
            job.status = "failed"
            job.stage = "failed"
            job.error = {"code": "TIMEOUT", "message": "导入租约多次超时，已停止重试"}
            _finish_attempt(db, job, error_code="TIMEOUT", error_summary="导入租约超时")
        else:
            _finish_attempt(
                db, job, error_code="TIMEOUT", error_summary="导入租约超时，等待重试"
            )
            job.status = "queued"
            job.stage = "queued"
            job.error = {"code": "TIMEOUT", "message": "导入租约超时，已重新排队"}
        job.lease_token = None
        job.lease_owner = None
        job.lease_expires_at = None
    if jobs:
        db.commit()
    return len(jobs)


def claim_next_dataset_import(
    db: Session, worker_id: str = "dataset-import-worker"
) -> tuple[str, str] | None:
    """使用 SKIP LOCKED 原子领取一个作业并写入短租约；仅返回标量避免跨 Session ORM。"""
    running = (
        db.query(DatasetImport)
        .filter(DatasetImport.status.in_(IN_PROGRESS_STATUSES))
        .count()
    )
    if running >= _max_running_dataset_imports(db):
        return None
    job = (
        db.query(DatasetImport)
        .filter(DatasetImport.status == "queued")
        .order_by(DatasetImport.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if not job:
        return None
    if job.attempt >= job.max_attempts:
        job.status = "failed"
        job.stage = "failed"
        job.error = {"code": "TIMEOUT", "message": "导入作业已达到最大尝试次数"}
        db.commit()
        return None
    lease_token = secrets.token_hex(24)
    job.attempt += 1
    job.status = "downloading"
    job.stage = "downloading"
    job.lease_token = lease_token
    job.lease_owner = worker_id
    job.lease_expires_at = utcnow() + timedelta(seconds=IMPORT_LEASE_SECONDS)
    job.error = {}
    db.add(
        DatasetImportAttempt(
            import_id=job.id,
            attempt_no=job.attempt,
            worker_id=worker_id,
            lease_token=lease_token,
            stage="downloading",
        )
    )
    db.commit()
    return job.id, lease_token


def _assert_safe_download_url(value: str, allowed_domains: set[str]) -> None:
    """在请求前检查 HTTPS、固定允许域名和非私网解析，降低导入 SSRF 风险。"""
    parsed = urlparse(value)
    hostname = parsed.hostname.lower() if parsed.hostname else None
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise ImportFailure("VALIDATION", "来源制品地址不符合 HTTPS 安全要求")
    if hostname not in allowed_domains:
        raise ImportFailure("VALIDATION", "来源制品地址不在已批准域名清单")
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImportFailure("UPSTREAM", "来源域名无法解析") from exc
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        ):
            raise ImportFailure("VALIDATION", "来源域名解析到不安全网络地址")


class _SafeRedirectHandler(HTTPRedirectHandler):
    """逐跳校验重定向目标，防止批准域名将 Worker 引向未审核位置。"""

    def __init__(self, allowed_domains: set[str]) -> None:
        super().__init__()
        self.allowed_domains = allowed_domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        """仅构造通过同一安全校验的重定向请求。"""
        _assert_safe_download_url(newurl, self.allowed_domains)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_artifact(url: str, allowed_domains: set[str]) -> bytes:
    """下载受限大小的单个制品，超限与网络异常按统一错误码归类。"""
    _assert_safe_download_url(url, allowed_domains)
    request = Request(
        url, headers={"User-Agent": "ai-eval-platform-dataset-import/1.0"}
    )
    opener = build_opener(_SafeRedirectHandler(allowed_domains))
    try:
        with opener.open(request, timeout=30) as response:
            content = response.read(IMPORT_MAX_ARTIFACT_BYTES + 1)
    except TimeoutError as exc:
        raise ImportFailure("TIMEOUT", "下载来源制品超时") from exc
    except HTTPError as exc:
        raise ImportFailure("UPSTREAM", "来源制品服务返回异常状态") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ImportFailure("TIMEOUT", "下载来源制品超时") from exc
        raise ImportFailure("UPSTREAM", "无法获取来源制品") from exc
    if len(content) > IMPORT_MAX_ARTIFACT_BYTES:
        raise ImportFailure("VALIDATION", "来源制品超过 50MB 上限")
    return content


def _parse_artifact(content: bytes, parser_kind: str) -> list[dict[str, Any]]:
    """解析固定 JSONL/CSV 格式；格式错误整体拒绝，不静默丢弃问题行。"""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFailure("VALIDATION", "来源制品必须使用 UTF-8 编码") from exc
    rows: list[dict[str, Any]] = []
    if parser_kind == "jsonl":
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ImportFailure(
                    "VALIDATION", f"来源制品第 {line_no} 行不是合法 JSON"
                ) from exc
            if not isinstance(value, dict):
                raise ImportFailure(
                    "VALIDATION", f"来源制品第 {line_no} 行必须是 JSON 对象"
                )
            rows.append(value)
    elif parser_kind == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ImportFailure("VALIDATION", "来源 CSV 缺少表头")
        rows = [dict(row) for row in reader]
    else:
        raise ImportFailure("VALIDATION", "未注册的受控解析器")
    if not rows:
        raise ImportFailure("VALIDATION", "来源制品没有可导入行")
    return rows


def _source_split(raw: dict[str, Any], artifact: dict[str, Any]) -> Any:
    """优先读取行级 split；缺失时使用制品级固定 split。"""
    return raw.get("split") if raw.get("split") is not None else artifact.get("split")


def _is_selected(
    raw: dict[str, Any], artifact: dict[str, Any], manifest: dict[str, Any]
) -> bool:
    """按冻结 split 和精确 filters 筛选行，筛选表达式不支持用户自定义代码。"""
    split = _source_split(raw, artifact)
    if not isinstance(split, str) or not split.strip():
        raise ImportFailure("VALIDATION", "来源制品行缺少可验证的 split")
    if split not in set(manifest.get("splits") or []):
        return False
    for key, expected in (manifest.get("filters") or {}).items():
        actual = raw.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _normalise_row(
    raw: dict[str, Any], row_no: int, provenance: dict[str, Any]
) -> DatasetImportRow:
    """将不同公开问答字段规约为平台 staging 三元组并保留其它字段为 extras。"""
    question = str(raw.get("question") or raw.get("q") or raw.get("prompt") or "")
    reference_value = raw.get("reference", raw.get("answer", raw.get("r", "")))
    reference = str(reference_value if reference_value is not None else "")
    context_value = raw.get("context", raw.get("c"))
    context = str(context_value) if context_value is not None else None
    extras = {
        key: value
        for key, value in raw.items()
        if key
        not in {"question", "q", "prompt", "reference", "answer", "r", "context", "c"}
    }
    warnings: list[str] = []
    if not question.strip():
        warnings.append("question_missing")
    if not reference.strip():
        warnings.append("reference_missing")
    canonical = json.dumps(
        {
            "question": question,
            "reference": reference,
            "context": context,
            "extras": extras,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return DatasetImportRow(
        import_id="",
        row_no=row_no,
        question=question,
        reference=reference,
        context=context,
        extras=extras,
        provenance=provenance,
        warnings=warnings,
        content_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _update_lease(
    db: Session, job: DatasetImport, lease_token: str, *, stage: str
) -> None:
    """仅当前持有者可推进作业阶段或延长租约，防止恢复 Worker 覆盖新尝试。"""
    if job.lease_token != lease_token or job.status not in IN_PROGRESS_STATUSES:
        raise ImportFailure("CONCURRENCY", "导入租约已失效")
    job.stage = stage
    job.status = stage
    job.lease_expires_at = utcnow() + timedelta(seconds=IMPORT_LEASE_SECONDS)
    attempt = (
        db.query(DatasetImportAttempt)
        .filter(
            DatasetImportAttempt.import_id == job.id,
            DatasetImportAttempt.lease_token == lease_token,
        )
        .first()
    )
    if attempt:
        attempt.stage = stage
    db.commit()


def _fail_dataset_import(
    import_id: str, lease_token: str, failure: ImportFailure
) -> None:
    """以租约令牌条件收束失败，避免旧 Worker 把已重试作业错误置失败。"""
    db = SessionLocal()
    try:
        job = (
            db.query(DatasetImport)
            .filter(
                DatasetImport.id == import_id, DatasetImport.lease_token == lease_token
            )
            .with_for_update()
            .first()
        )
        if not job:
            return
        job.status = "failed"
        job.stage = "failed"
        job.error = {"code": failure.code, "message": failure.message}
        _finish_attempt(db, job, error_code=failure.code, error_summary=failure.message)
        job.lease_token = None
        job.lease_owner = None
        job.lease_expires_at = None
        db.commit()
    finally:
        db.close()


def run_dataset_import(import_id: str, lease_token: str) -> None:
    """执行一次已领取导入：下载验真、解析筛选、写 staging，失败时安全收束。"""
    db = SessionLocal()
    try:
        job = (
            db.query(DatasetImport)
            .filter(
                DatasetImport.id == import_id, DatasetImport.lease_token == lease_token
            )
            .with_for_update()
            .first()
        )
        if not job:
            return
        manifest = job.manifest or {}
        parser_kind = SUPPORTED_PARSERS.get(str(manifest.get("parser_id") or ""))
        if not parser_kind:
            raise ImportFailure("VALIDATION", "当前 release 未配置受支持的受控解析器")
        release_manifest = manifest.get("release_manifest")
        artifacts = (
            release_manifest.get("artifacts")
            if isinstance(release_manifest, dict)
            else None
        )
        if not isinstance(artifacts, list) or not artifacts:
            raise ImportFailure("VALIDATION", "冻结 manifest 缺少制品清单")
        catalog_entry = manifest.get("catalog_entry")
        allowed_domains = (
            set(catalog_entry.get("allowed_domains") or [])
            if isinstance(catalog_entry, dict)
            else set()
        )
        if not allowed_domains:
            raise ImportFailure("VALIDATION", "冻结 manifest 缺少来源允许域名")
        _update_lease(db, job, lease_token, stage="downloading")
        parsed_rows: list[DatasetImportRow] = []
        artifact_records: list[tuple[str, str, int, str | None]] = []
        for artifact_index, artifact in enumerate(artifacts, start=1):
            if not isinstance(artifact, dict) or not isinstance(
                artifact.get("url"), str
            ):
                raise ImportFailure("VALIDATION", "冻结 manifest 包含无效制品")
            content = _download_artifact(artifact["url"], allowed_domains)
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if actual_sha256.lower() != str(artifact.get("sha256") or "").lower():
                raise ImportFailure("VALIDATION", "来源制品 SHA-256 校验失败")
            artifact_rows = _parse_artifact(content, parser_kind)
            artifact_name = str(artifact.get("name") or f"artifact-{artifact_index}")
            artifact_records.append(
                (artifact_name, actual_sha256, len(content), artifact.get("media_type"))
            )
            for source_row_no, raw in enumerate(artifact_rows, start=1):
                if not _is_selected(raw, artifact, manifest):
                    continue
                if len(parsed_rows) >= IMPORT_MAX_ROWS:
                    raise ImportFailure("VALIDATION", "筛选后的导入行数超过 20000 上限")
                parsed_rows.append(
                    _normalise_row(
                        raw,
                        len(parsed_rows) + 1,
                        {
                            "artifact_name": artifact_name,
                            "artifact_sha256": actual_sha256,
                            "source_row_no": source_row_no,
                            # split 随来源快照冻结，staging 编辑不能伪造来源分组。
                            "split": _source_split(raw, artifact),
                            "release_manifest_hash": manifest.get(
                                "release_manifest_hash"
                            ),
                        },
                    )
                )
        if not parsed_rows:
            raise ImportFailure("VALIDATION", "筛选条件未产生可导入行")
        _update_lease(db, job, lease_token, stage="validating")
        _update_lease(db, job, lease_token, stage="parsing")
        db.query(DatasetImportRow).filter(DatasetImportRow.import_id == job.id).delete(
            synchronize_session=False
        )
        db.query(DatasetSourceArtifact).filter(
            DatasetSourceArtifact.import_id == job.id
        ).delete(synchronize_session=False)
        for artifact_name, digest, size_bytes, media_type in artifact_records:
            db.add(
                DatasetSourceArtifact(
                    import_id=job.id,
                    artifact_name=artifact_name,
                    sha256=digest,
                    size_bytes=size_bytes,
                    media_type=media_type,
                )
            )
        for row in parsed_rows:
            row.import_id = job.id
            db.add(row)
        job.status = "review_ready"
        job.stage = "review_ready"
        job.staging_revision += 1
        job.summary = {
            "source_rows": len(parsed_rows),
            "artifact_count": len(artifact_records),
            "warning_rows": sum(1 for row in parsed_rows if row.warnings),
        }
        _finish_attempt(db, job)
        job.lease_token = None
        job.lease_owner = None
        job.lease_expires_at = None
        db.commit()
    except ImportFailure as exc:
        db.rollback()
        _fail_dataset_import(import_id, lease_token, exc)
    except Exception as exc:
        db.rollback()
        _fail_dataset_import(
            import_id, lease_token, ImportFailure("INTERNAL", "导入执行失败")
        )
        print(
            f"[worker] dataset import failed import={import_id} type={type(exc).__name__}",
            flush=True,
        )
    finally:
        db.close()
