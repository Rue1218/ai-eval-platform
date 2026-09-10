"""外部白名单基目录路径解析测试（read/write/edit 绝对路径）。"""

from __future__ import annotations

import os

import pytest

from app.config import settings
from app.errors import AppError
from app.harness.execution.dispatch import _resolve_safe_path


def test_absolute_path_inside_base_allowed(monkeypatch, tmp_path) -> None:
    base = tmp_path / "ext"
    base.mkdir()
    (base / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings, "external_base_dir", str(base))
    assert _resolve_safe_path(str(base / "a.txt"), str(tmp_path / "ws")) == os.path.realpath(
        str(base / "a.txt")
    )


def test_absolute_path_outside_base_rejected(monkeypatch, tmp_path) -> None:
    base = tmp_path / "ext"
    base.mkdir()
    monkeypatch.setattr(settings, "external_base_dir", str(base))
    for bad in ("/etc/passwd", str(tmp_path / "other"), str(base / ".." / "escape")):
        with pytest.raises(AppError):
            _resolve_safe_path(bad, str(tmp_path / "ws"))


def test_symlink_escape_rejected(monkeypatch, tmp_path) -> None:
    base = tmp_path / "ext"
    base.mkdir()
    link = base / "escape"
    try:
        os.symlink("/etc", str(link))
    except OSError:
        pytest.skip("当前环境无符号链接权限")
    monkeypatch.setattr(settings, "external_base_dir", str(base))
    with pytest.raises(AppError):
        _resolve_safe_path(str(link / "passwd"), str(tmp_path / "ws"))


def test_absolute_path_rejected_when_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "external_base_dir", "")
    with pytest.raises(AppError):
        _resolve_safe_path("/tmp/x", str(tmp_path))


def test_relative_path_still_confined_to_workspace(tmp_path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    assert _resolve_safe_path("sub/f.txt", str(root)) == os.path.realpath(str(root / "sub" / "f.txt"))
    with pytest.raises(AppError):
        _resolve_safe_path("../escape", str(root))
