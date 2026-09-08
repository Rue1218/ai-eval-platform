"""F5/G6 磁盘配额测试（《工作区与沙箱设计方案》§6.6 / M-R3-4）。

覆盖：写前容量检查（每目录配额 + extra 净增）、卷水位熔断优先于配额、配额
关闭语义、缓存失效后重算、dispatch 直写/编辑挂点（超限拒绝且不留半成品）。
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.execution.dispatch import edit_file_safe, write_file_safe
from app.harness.execution.quota import (
    check_workspace_write_capacity,
    directory_usage_cached,
    invalidate_usage_cache,
)


@pytest.fixture()
def _quota_small(monkeypatch, tmp_path) -> str:
    monkeypatch.setattr(settings, "workspace_quota_bytes", 200)
    monkeypatch.setattr(settings, "sandbox_volume_watermark_bytes", 0)  # 关水位
    (tmp_path / "seed.txt").write_text("x" * 150, encoding="utf-8")
    return str(tmp_path)


def test_write_rejected_when_projected_exceeds_quota(_quota_small) -> None:
    """现有用量 150B + extra 100B > 配额 200B → 拒（明确文案，VALIDATION）。"""
    with pytest.raises(AppError) as exc:
        check_workspace_write_capacity(_quota_small, extra_bytes=100)
    assert exc.value.code == ErrorCode.VALIDATION
    assert "配额" in exc.value.message


def test_write_allowed_within_quota(_quota_small) -> None:
    """现有 150B + extra 40B ≤ 200B → 放行。"""
    check_workspace_write_capacity(_quota_small, extra_bytes=40)


def test_quota_disabled_skips_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "workspace_quota_bytes", 0)
    monkeypatch.setattr(settings, "sandbox_volume_watermark_bytes", 0)
    (tmp_path / "big").write_text("x" * 10**6, encoding="utf-8")
    check_workspace_write_capacity(str(tmp_path), extra_bytes=10**6)  # 不拒


def test_volume_watermark_takes_precedence(monkeypatch, tmp_path) -> None:
    """水位熔断优先于每目录配额（全局末防线）。"""
    monkeypatch.setattr(settings, "workspace_quota_bytes", 0)  # 配额关
    monkeypatch.setattr(settings, "sandbox_volume_watermark_bytes", 10)

    class _Low:
        free = 5  # 低于水位 → 拒

    monkeypatch.setattr(
        "app.harness.execution.quota.shutil.disk_usage", lambda _path: _Low()
    )
    with pytest.raises(AppError) as exc:
        check_workspace_write_capacity(str(tmp_path), extra_bytes=0)
    assert "水位" in exc.value.message

    class _Room:
        free = 999

    monkeypatch.setattr(
        "app.harness.execution.quota.shutil.disk_usage", lambda _path: _Room()
    )
    check_workspace_write_capacity(str(tmp_path), extra_bytes=0)  # 放行


def test_invalidate_recomputes_usage(_quota_small) -> None:
    """标脏后缓存重算（新写入被后续检查可见）。"""
    usage_dir = _quota_small
    assert directory_usage_cached(usage_dir) == 150
    with open(usage_dir + "/more.txt", "w", encoding="utf-8") as handle:
        handle.write("x" * 300)
    invalidate_usage_cache(usage_dir)
    assert directory_usage_cached(usage_dir) == 450
    with pytest.raises(AppError):
        check_workspace_write_capacity(usage_dir, extra_bytes=0)  # 450 > 200


def test_write_file_safe_quota_rejects_and_leaves_nothing(monkeypatch, tmp_path) -> None:
    """直写挂点：现有用量 + 新文件超配额 → 拒且不产生半成品文件。"""
    monkeypatch.setattr(settings, "workspace_quota_bytes", 100)
    monkeypatch.setattr(settings, "sandbox_volume_watermark_bytes", 0)
    (tmp_path / "seed.txt").write_text("x" * 80, encoding="utf-8")
    root = str(tmp_path)
    with pytest.raises(AppError) as exc:
        write_file_safe("a.txt", "x" * 80, root)  # 80 + 80 > 100
    assert exc.value.code == ErrorCode.VALIDATION
    assert not (tmp_path / "a.txt").exists()
    # 配额内写入放行且文件可读（直写路径正常）
    result = write_file_safe("b.txt", "x" * 19, root)
    assert result.bytes_written == 19


def test_edit_file_safe_quota_rejects_net_growth(monkeypatch, tmp_path) -> None:
    """edit 净增挂点：改写后总量超配额拒（净增按新旧字节差计算）。"""
    monkeypatch.setattr(settings, "workspace_quota_bytes", 200)
    monkeypatch.setattr(settings, "sandbox_volume_watermark_bytes", 0)
    root = tmp_path
    (root / "t.txt").write_text("abcdef", encoding="utf-8")  # 6B
    with pytest.raises(AppError) as exc:
        edit_file_safe("t.txt", "abcdef", "y" * 250, str(root))  # 净增 244 → 250 > 200
    assert exc.value.code == ErrorCode.VALIDATION
    # 原文件未被改动（原子拒绝）
    assert (root / "t.txt").read_text(encoding="utf-8") == "abcdef"


def test_edit_file_safe_net_shrink_allowed_within_quota(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "workspace_quota_bytes", 200)
    monkeypatch.setattr(settings, "sandbox_volume_watermark_bytes", 0)
    root = tmp_path
    (root / "t.txt").write_text("x" * 190, encoding="utf-8")
    result = edit_file_safe("t.txt", "x" * 190, "short", str(root))  # 净增为负
    assert result.replacements == 1
