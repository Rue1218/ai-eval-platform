"""工作区磁盘配额与共享卷水位（F5/G6 §6.6）。

语义要点（《工作区与沙箱设计方案》V0.6 §6.6 / M-R3-4）：

- **每工作区配额（软上限）**：数据卷无内核级目录配额（非 xfs prjquota 部署）时
  写前检查 + du 记账承担——``check_workspace_write_capacity`` 在每次直写/
  workspace-write bash 执行前核算目录用量（TTL 缓存防每写全量 walk），
  超限即拒（VALIDATION 明确文案，不静默）；
- **卷级水位熔断（全局末防线）**：剩余空间 < 阈值 → 整体拒写，判定**优先于**
  每目录配额；只挂写路径（read-only 试跑、读工具与 none 档不受影响）；
- 错误码用 VALIDATION：配额/水位拒写**不触发升档审批链**（区别于 read-only
  EROFS 的 DENIED——workspace-write 已是可写档，配额拒写再升档无意义且浪费
  一次重放）；单命令洪水（dd 等）为有界残余（上限 = 卷水位，下轮调用熔断）。
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time

from app.config import settings
from app.errors import AppError, ErrorCode

logger = logging.getLogger("ai-eval.harness.quota")

# 目录用量 TTL 缓存（防每次写前全量 os.walk）：键 = 目录，值 = (记账时刻, 字节)
_QUOTA_CACHE_TTL_S = 10.0
_USAGE_CACHE: dict[str, tuple[float, int]] = {}
_USAGE_LOCK = threading.Lock()


def invalidate_usage_cache(root: str) -> None:
    """直写成功后标脏目录用量缓存（下一次检查重新核算）。"""
    with _USAGE_LOCK:
        _USAGE_CACHE.pop(root, None)


def _directory_usage_bytes(root: str) -> int:
    """目录树总字节（os.walk + getsize；单文件损坏忽略，不影响配额判定）。"""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    continue
    except OSError as exc:
        logger.debug("配额核算目录不可读 dir=%s err=%s", root, exc)
        return 0
    return total


def directory_usage_cached(root: str) -> int:
    """TTL 缓存的目录用量（秒级记账，防每写全量 walk 拖慢工具链）。"""
    now = time.monotonic()
    with _USAGE_LOCK:
        cached = _USAGE_CACHE.get(root)
        if cached and now - cached[0] < _QUOTA_CACHE_TTL_S:
            return cached[1]
    total = _directory_usage_bytes(root)
    with _USAGE_LOCK:
        _USAGE_CACHE[root] = (time.monotonic(), total)
    return total


def _volume_free_bytes(path: str) -> int:
    """path 所在文件系统剩余空间（磁盘配额语义按卷而非目录）。"""
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or path)
    except OSError as exc:
        logger.warning("卷水位核算失败 path=%s err=%s（按放行处理，配额仍生效）", path, exc)
        return int(settings.sandbox_volume_watermark_bytes)
    return usage.free


def check_workspace_write_capacity(
    sandbox_dir: str,
    *,
    extra_bytes: int = 0,
    invalidate_after: bool = False,
) -> None:
    """workspace-write 写前容量检查（§6.6）：卷水位熔断优先 → 每目录配额。

    ``extra_bytes`` = 本次预计新增字节（直写工具传新文件大小或 edit 净增；
    bash 写不可预估传 0——只按现有用量判定）。超限抛 VALIDATION（不触发
    升档链）。``invalidate_after`` = 调用方写成功后标脏用量缓存。
    """
    watermark = int(settings.sandbox_volume_watermark_bytes)
    if watermark > 0:
        free = _volume_free_bytes(sandbox_dir)
        if free < watermark:
            raise AppError(
                ErrorCode.VALIDATION,
                "沙箱卷空间不足（水位熔断）：写入已被拒绝，请稍后重试或联系管理员",
            )
    quota = int(settings.workspace_quota_bytes)
    if quota <= 0:
        return
    used = directory_usage_cached(sandbox_dir)
    projected = used + max(0, int(extra_bytes))
    if projected > quota:
        raise AppError(
            ErrorCode.VALIDATION,
            "工作区写入配额已超限：请先清理工作区文件或联系管理员扩容"
            f"（当前约 {_human_bytes(used)} / 上限 {_human_bytes(quota)}）",
        )
    if invalidate_after:
        invalidate_usage_cache(sandbox_dir)


def _human_bytes(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{value}B"
        value /= 1024
    return f"{value}GB"
