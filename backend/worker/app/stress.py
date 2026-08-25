"""压测执行器：Worker 下发到 stress 容器，轮询状态并写报告 / 时序曲线。

禁止在 api / WS 进程内发压。取消时立即 POST /stop，尽快停发（与评测
「当前样本结束后停」不同）。报告 metrics 同时写 API.md 字段与前端 KPI 别名。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .db import SessionLocal
from .events import push_ws
from .models import ProtocolProfile, Report, Setting, Task, TaskEvent
from .profile_env import profile_connection
from .task_state import claim_running_task_for_terminal_write, is_cancelled

logger = logging.getLogger("worker.stress")

DEFAULT_STRESS_URL = "http://stress:19090"
DEFAULT_MAX_QPS = 500
DEFAULT_MAX_DURATION_S = 1800
POLL_INTERVAL_S = 1.0


def _service_base_url(base_url: str) -> str:
    """与 protocol.py 相同：去掉末尾 /v1，避免拼出 /v1/v1。"""
    base = base_url.strip().rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _now() -> datetime:
    return datetime.now(UTC)


def _stress_base() -> str:
    return os.environ.get("STRESS_URL", DEFAULT_STRESS_URL).rstrip("/")


def _request_json(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = 15.0,
) -> dict:
    """调用 stress 容器 HTTP JSON 接口；不把请求体写入日志。"""
    url = f"{_stress_base()}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
    except HTTPError as exc:
        raise RuntimeError(f"STRESS_HTTP_{exc.code}") from exc
    except TimeoutError as exc:
        raise RuntimeError("STRESS_TIMEOUT") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise RuntimeError("STRESS_TIMEOUT") from exc
        raise RuntimeError("STRESS_UNAVAILABLE") from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("STRESS_BAD_RESPONSE") from exc
    return parsed if isinstance(parsed, dict) else {}


def _load_stress_settings(db: Session) -> dict[str, Any]:
    row = db.query(Setting).filter(Setting.key == "stress").first()
    value = row.value if row and isinstance(row.value, dict) else {}
    return {
        "host_whitelist": value.get("host_whitelist") or [],
        "max_qps": int(value.get("max_qps") or DEFAULT_MAX_QPS),
        "max_duration_s": int(value.get("max_duration_s") or DEFAULT_MAX_DURATION_S),
        "price_per_1k_tokens": float(value.get("price_per_1k_tokens") or 0.002),
    }


def host_allowed(url: str, whitelist: object, env: str) -> bool:
    """目标 Host 必须在白名单内；名单为空时仅非 prod 放行（便于本地演示）。"""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    entries: list[str] = []
    if isinstance(whitelist, list):
        for item in whitelist:
            if isinstance(item, str) and item.strip():
                entries.append(item.strip().lower())
            elif isinstance(item, dict) and item.get("status", "active") == "active":
                raw = str(item.get("host") or "").strip().lower()
                if raw:
                    entries.append(raw)
    if not entries:
        return env != "prod"
    return any(host == allowed or host.endswith("." + allowed) for allowed in entries)


def clamp_stress(qps: object, duration_s: object, settings: dict[str, Any]) -> tuple[int, int]:
    """按平台 max_qps / max_duration_s 夹紧发压参数。"""
    max_qps = max(1, int(settings.get("max_qps") or DEFAULT_MAX_QPS))
    max_duration = max(1, int(settings.get("max_duration_s") or DEFAULT_MAX_DURATION_S))
    try:
        qps_i = int(qps)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        qps_i = 10
    try:
        dur_i = int(duration_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        dur_i = 120
    if isinstance(qps, bool) or qps_i < 1:
        qps_i = 10
    if isinstance(duration_s, bool) or dur_i < 1:
        dur_i = 120
    return min(qps_i, max_qps), min(dur_i, max_duration)


def _build_probe(profile: ProtocolProfile) -> tuple[str, str, dict[str, str], dict[str, Any]]:
    """按协议档拼一条低成本探测请求（不含 Key 日志）。"""
    base_url, model, api_key = profile_connection(profile, allow_global_alias=True)
    if not base_url or not model:
        raise ValueError("missing_target")
    base = _service_base_url(base_url)
    headers = {"Content-Type": "application/json"}
    ping = [{"role": "user", "content": "ping"}]
    if profile.protocol == "openai_responses":
        url = f"{base}/v1/responses"
        body: dict[str, Any] = {"model": model, "input": ping, "max_output_tokens": 8}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif profile.protocol == "anthropic_messages":
        url = f"{base}/v1/messages"
        body = {"model": model, "messages": ping, "max_tokens": 8}
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = profile.anthropic_version or "2023-06-01"
    else:
        url = f"{base}/v1/chat/completions"
        body = {"model": model, "messages": ping, "max_tokens": 8, "temperature": 0}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    return url, model, headers, body


def resolve_job(db: Session, task: Task) -> dict[str, Any]:
    """从父质量任务协议档解析发压目标，并套白名单 / 上限。"""
    config = task.config if isinstance(task.config, dict) else {}
    stress_cfg = config.get("stress") if isinstance(config.get("stress"), dict) else {}
    env = str(stress_cfg.get("env") or "test")
    settings = _load_stress_settings(db)
    qps, duration_s = clamp_stress(stress_cfg.get("qps"), stress_cfg.get("duration_s"), settings)

    parent_id = task.parent_task_id or config.get("parent_task_id")
    parent = db.query(Task).filter(Task.id == parent_id).first() if parent_id else None
    profile_ids: list[str] = []
    if parent and isinstance(parent.config, dict):
        raw_ids = parent.config.get("profile_ids") or []
        if isinstance(raw_ids, list):
            profile_ids = [str(item) for item in raw_ids if item]
    if not profile_ids and isinstance(config.get("profile_ids"), list):
        profile_ids = [str(item) for item in config["profile_ids"] if item]
    if not profile_ids:
        raise ValueError("missing_profile")
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_ids[0]).first()
    if not profile:
        raise ValueError("missing_profile")
    url, model, headers, body = _build_probe(profile)
    if not host_allowed(url, settings.get("host_whitelist"), env):
        raise PermissionError("whitelist")
    sla = stress_cfg.get("sla_p99_ms")
    job = {
        "task_id": task.id,
        "env": env,
        "model": model,
        "url": url,
        "method": "POST",
        "headers": headers,
        "body": body,
        "qps": qps,
        "duration_s": duration_s,
    }
    if sla is not None:
        try:
            job["sla_p99_ms"] = int(sla)
        except (TypeError, ValueError):
            pass
    return job


def metrics_from_status(status: dict[str, Any], *, sla_p99_ms: int | None) -> dict[str, Any]:
    """把引擎快照映射为报告 metrics（含前端 KPI 别名）。"""
    series = status.get("time_series") if isinstance(status.get("time_series"), list) else []
    points: list[dict[str, Any]] = []
    peak = 0.0
    for item in series:
        if not isinstance(item, dict):
            continue
        qps = float(item.get("qps") or 0)
        peak = max(peak, qps)
        points.append(
            {
                "ts": item.get("ts"),
                "qps": qps,
                "rt_ms": item.get("rt_ms"),
                "error_rate": item.get("error_rate"),
            }
        )
    achieved = float(status.get("qps") or peak or 0)
    rt = float(status.get("rt") or 0)
    p99 = float(status.get("p99_ms") or 0)
    error_rate = float(status.get("error_rate") or 0)
    sla_met = status.get("sla_met")
    metrics: dict[str, Any] = {
        "qps": round(achieved, 3),
        "rt": round(rt, 3),
        "error_rate": round(error_rate, 6),
        "p99_ms": round(p99, 3),
        "est_cost_usd": 0.0,
        "time_series": points,
        "series": points,
        "qps_peak": round(peak or achieved, 3),
        "p99": round(p99, 3),
        "est_cost": 0.0,
    }
    if sla_p99_ms is not None:
        metrics["sla_p99_ms"] = sla_p99_ms
        if isinstance(sla_met, bool):
            metrics["sla_met"] = sla_met
        else:
            metrics["sla_met"] = p99 <= sla_p99_ms if p99 else None
    return metrics


def _progress(db: Session, task_id: str, percent: int, message: str) -> None:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return
    percent = max(0, min(100, int(percent)))
    task.progress = {"percent": percent, "done": percent, "total": 100, "message": message}
    db.add(
        TaskEvent(
            task_id=task.id,
            event="progress",
            message=message,
            payload={"percent": percent, "done": percent, "total": 100},
        )
    )
    db.commit()
    push_ws(
        task.session_id,
        "progress",
        {"percent": percent, "done": percent, "total": 100, "message": message},
        task_id=task.id,
    )


def _upsert_report(db: Session, task: Task, metrics: dict[str, Any]) -> Report:
    report = db.query(Report).filter(Report.task_id == task.id).first()
    if report is None:
        report = Report(task_id=task.id, kind="stress", metrics=metrics)
        db.add(report)
        db.flush()
    else:
        report.metrics = metrics
        flag_modified(report, "metrics")
    return report


def _fail(db: Session, task_id: str, code: str, message: str) -> None:
    task = claim_running_task_for_terminal_write(db, task_id)
    if not task:
        logger.info("stress task %s skipped failure because it is no longer running", task_id)
        return
    task.status = "failed"
    task.finished_at = _now()
    db.add(
        TaskEvent(
            task_id=task.id,
            event="error",
            message=message,
            payload={"code": code},
        )
    )
    db.commit()
    push_ws(
        task.session_id,
        "error",
        {"code": code, "message": message},
        task_id=task.id,
    )
    logger.info("stress task %s failed code=%s", task_id, code)


def _stop_engine(task_id: str) -> None:
    try:
        _request_json("POST", "/stop", {"task_id": task_id}, timeout=5.0)
    except Exception:
        logger.info("stress stop 调用失败 task=%s", task_id)


def run_stress(task_id: str) -> None:
    """领取后的压测主流程：下发 → 轮询取消 → 写报告。"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error("stress task %s not found", task_id)
            return
        try:
            job = resolve_job(db, task)
        except PermissionError:
            _fail(db, task_id, "WHITELIST", "目标 Host 不在压测白名单")
            return
        except ValueError as exc:
            if str(exc) == "missing_profile":
                _fail(db, task_id, "VALIDATION", "压测缺少被测协议档")
            else:
                _fail(db, task_id, "VALIDATION", "压测缺少目标地址")
            return
        except Exception:
            logger.exception("stress resolve failed task=%s", task_id)
            _fail(db, task_id, "INTERNAL", "压测目标解析失败")
            return

        sla = job.get("sla_p99_ms")
        sla_i = int(sla) if isinstance(sla, int) else None
        duration_s = int(job["duration_s"])
        # 发给引擎的 JSON 含鉴权头，此后不得打印 job。
        try:
            _request_json("POST", "/run", job, timeout=15.0)
        except RuntimeError as exc:
            code = str(exc)
            if code == "STRESS_TIMEOUT":
                _fail(db, task_id, "TIMEOUT", "压测引擎超时")
            else:
                _fail(db, task_id, "UPSTREAM", "压测引擎不可用")
            return

        _progress(db, task_id, 1, "发压中")
        started = time.monotonic()
        last_status: dict[str, Any] = {}
        while True:
            if is_cancelled(db, task_id):
                _stop_engine(task_id)
                logger.info("stress task %s cancelled, stop issued", task_id)
                return
            try:
                last_status = _request_json(
                    "GET", f"/status?task_id={task_id}", timeout=10.0
                )
            except RuntimeError as exc:
                if time.monotonic() - started > duration_s + 30:
                    _fail(db, task_id, "UPSTREAM", "压测引擎状态不可用")
                    return
                if str(exc) == "STRESS_TIMEOUT":
                    time.sleep(POLL_INTERVAL_S)
                    continue
                _fail(db, task_id, "UPSTREAM", "压测引擎不可用")
                return

            metrics = metrics_from_status(last_status, sla_p99_ms=sla_i)
            task_row = db.query(Task).filter(Task.id == task_id).first()
            if task_row:
                report = _upsert_report(db, task_row, metrics)
                task_row.report_id = report.id
                db.commit()

            elapsed = time.monotonic() - started
            percent = min(99, int(elapsed * 100 / max(duration_s, 1)))
            _progress(db, task_id, percent, "发压中")

            status = str(last_status.get("status") or "")
            if status in {"done", "stopped", "failed"}:
                break
            if elapsed > duration_s + 90:
                _stop_engine(task_id)
                _fail(db, task_id, "TIMEOUT", "压测超过预期时长")
                return
            time.sleep(POLL_INTERVAL_S)

        if is_cancelled(db, task_id):
            return
        if str(last_status.get("status") or "") == "stopped":
            return
        if str(last_status.get("status") or "") == "failed":
            _fail(db, task_id, "UPSTREAM", "压测执行失败")
            return

        task = claim_running_task_for_terminal_write(db, task_id)
        if not task:
            return
        metrics = metrics_from_status(last_status, sla_p99_ms=sla_i)
        report = _upsert_report(db, task, metrics)
        task.status = "succeeded"
        task.finished_at = _now()
        task.report_id = report.id
        task.result = {"kind": "stress", "qps": metrics.get("qps"), "error_rate": metrics.get("error_rate")}
        db.add(TaskEvent(task_id=task.id, event="finish", payload={"status": "succeeded"}))
        db.commit()
        _progress(db, task_id, 100, "压测完成")
        push_ws(task.session_id, "report", {"report_id": report.id}, task_id=task.id)
        logger.info("stress task %s succeeded", task_id)
        print(f"[worker] succeeded task={task_id} kind=stress", flush=True)
    except Exception:
        logger.exception("stress task %s execution error", task_id)
        try:
            _fail(db, task_id, "INTERNAL", "压测执行失败")
        except Exception:
            db.rollback()
            logger.exception("stress task %s failed-status persist error", task_id)
    finally:
        db.close()
