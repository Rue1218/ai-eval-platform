"""代码评审修复回归测试（2026-09-07 评审批）。

覆盖：
- BLK-2：``resolve_session_sandbox_db`` 行态校验——工作区注销/行缺失 →
  VALIDATION fail-closed，不回落 legacy；
- BLK-1：附件 staging 与沙箱根同源——``stage_attachments`` 落在给定
  workspace_dir/attachments 下（而非 legacy 会话目录）；
- MAJ-1：``execute_raw`` VALIDATION 错误把可读原因放 message（模型可见），
  内部错误保持通用文案；
- runner 侧 /run/stream × BUSY 协议帧由 ``backend/runner/tests`` 覆盖。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import AppError, ErrorCode
from app.workspace_service import resolve_session_sandbox_db

_WS_ID = "c09bd564-1443-4a2e-b085-70e719818d08"
_SID = "a09bd564-1443-4a2e-b085-70e719818d09"


class _FakeDb:
    """最小桩：query(Workspace).filter(...).first() 返回预置行。"""

    def __init__(self, ws_row: object | None) -> None:
        self._ws = ws_row

    def query(self, _model: object) -> _FakeDb:
        return self

    def filter(self, *_a: object, **_k: object) -> _FakeDb:
        return self

    def first(self) -> object | None:
        return self._ws


def _workspace_row(*, deleted: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=_WS_ID,
        deleted_at=datetime.now(UTC) if deleted else None,
    )


@pytest.fixture()
def tmp_root(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(root))
    return root


# ─── BLK-2：行态校验 fail-closed ───


def test_resolve_db_rejects_soft_deleted_workspace(tmp_root) -> None:
    """工作区已注销（deleted_at 非空）→ VALIDATION，绝不回落 legacy 目录。"""
    (tmp_root / _WS_ID).mkdir()
    fake = _FakeDb(_workspace_row(deleted=True))
    with pytest.raises(AppError) as exc:
        resolve_session_sandbox_db(fake, _SID, _WS_ID, "")
    assert exc.value.code == ErrorCode.VALIDATION
    assert not os.path.exists(os.path.join(str(tmp_root), _SID))


def test_resolve_db_rejects_missing_workspace_row(tmp_root) -> None:
    """工作区行缺失（不一致窗口）→ VALIDATION。"""
    (tmp_root / _WS_ID).mkdir()
    with pytest.raises(AppError) as exc:
        resolve_session_sandbox_db(_FakeDb(None), _SID, _WS_ID, "")
    assert exc.value.code == ErrorCode.VALIDATION


def test_resolve_db_active_workspace_returns_scope(tmp_root) -> None:
    """活跃工作区 → 返回 scope 目录（含嵌套段）。"""
    base = tmp_root / _WS_ID
    (base / "cases").mkdir(parents=True)
    fake = _FakeDb(_workspace_row(deleted=False))
    result = resolve_session_sandbox_db(fake, _SID, _WS_ID, "cases")
    assert result == os.path.abspath(str(base / "cases"))


def test_resolve_db_unbound_keeps_legacy(tmp_root) -> None:
    """未绑定（workspace_id=None）→ legacy 自动目录（行为不变）。"""
    fake = _FakeDb(None)
    result = resolve_session_sandbox_db(fake, _SID, None, None)
    assert result == os.path.join(str(tmp_root), _SID)
    assert os.path.isdir(result)


# ─── BLK-1：附件 staging 与沙箱根同源 ───


def _fake_file(name: str = "notes.md") -> SimpleNamespace:
    return SimpleNamespace(id=f"file-{uuid4().hex[:8]}", filename=name, storage_path="")


def test_stage_attachments_lands_under_given_workspace_dir(tmp_path) -> None:
    """附件只落在传入 workspace_dir/attachments 下（绑定会话根同源）。"""
    from app.agent.attachments import stage_attachments

    workspace_dir = str(tmp_path / "ws-scope")
    os.makedirs(workspace_dir)
    source = tmp_path / "source.md"
    source.write_text("hello", encoding="utf-8")
    stored = _fake_file()
    stored.storage_path = str(source)

    stage_attachments(workspace_dir, [stored])

    target = os.path.join(workspace_dir, "attachments", f"{stored.id}-notes.md")
    assert os.path.isfile(target)
    with open(target, encoding="utf-8") as handle:
        assert handle.read() == "hello"
    # 绝不写入 legacy 会话目录形态的路径（同源承诺）
    assert not os.path.exists(os.path.join(str(tmp_path), "attachments"))


def test_stage_attachments_skips_non_text_and_missing(tmp_path) -> None:
    """非文本/源缺失附件不落盘（幂等安全）。"""
    from app.agent.attachments import stage_attachments

    workspace_dir = str(tmp_path / "ws")
    os.makedirs(workspace_dir)
    stage_attachments(workspace_dir, [])
    stage_attachments(workspace_dir, [_fake_file("img.png")])
    stage_attachments(workspace_dir, [_fake_file("missing.md")])
    attach_dir = os.path.join(workspace_dir, "attachments")
    # 空/非文本/源缺失不产生任何落盘文件（目录可能因 create 预建）
    if os.path.isdir(attach_dir):
        assert os.listdir(attach_dir) == []


# ─── MAJ-1：VALIDATION 可读原因直达模型 ───


def _run_execute_raw(handler) -> object:
    import app.harness.execution.dispatch as dispatch

    return dispatch.execute_raw(
        SimpleNamespace(name="bash", call_id="c1", arguments={"command": "x"}),
        timeout_s=1.0,
        permission="sandbox.bash",
        handler=handler,
        sandbox_dir="/tmp",
    )


def test_execute_raw_validation_keeps_readable_message() -> None:
    """VALIDATION 错误 message 保真（模型可见 stderr 摘要），非通用文案。"""
    from app.errors import AppError

    def failing_handler(*_a: object, **_k: object) -> object:
        raise AppError(ErrorCode.VALIDATION, "命令执行失败（exit 1）：permission denied")

    result = _run_execute_raw(failing_handler)
    error = result.error  # type: ignore[attr-defined]
    assert error["code"] == "VALIDATION"
    assert "permission denied" in str(error["message"])
    assert error["message"] != "操作失败（VALIDATION）"


def test_execute_raw_internal_keeps_generic_message() -> None:
    """INTERNAL 错误保持通用文案（不泄露内部细节）。"""
    from app.errors import AppError

    def failing_handler(*_a: object, **_k: object) -> object:
        raise AppError(ErrorCode.INTERNAL, "内部堆栈细节 secret")

    result = _run_execute_raw(failing_handler)
    error = result.error  # type: ignore[attr-defined]
    assert error["code"] == "INTERNAL"
    assert "secret" not in str(error["message"])
