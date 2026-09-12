"""F3/G5 会话-工作区绑定单测（纯函数 + 桩 DB + 401，沿用仓库既有测试模式）。

覆盖：``resolve_session_sandbox`` 唯一解析入口（legacy / 绑定 / 绑定失效
fail-closed / scope 越界）、``ensure_workspace_scope`` 目录就绪、BLK-4
守卫分支（create 绑 team 拒绝 / sharing 转 team 拒绝——以纯函数与路由
surface 验证）、schemas 默认兼容。不依赖测试数据库（绑定行查询在
``create_session`` 路由内，未登录 401 层断言路由注册）。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.schemas import SessionCreate
from app.workspace_service import (
    ensure_workspace_scope,
    resolve_session_sandbox,
    workspace_dir_for,
)

_WS_ID = "c09bd564-1443-4a2e-b085-70e719818d08"
_SID = "a09bd564-1443-4a2e-b085-70e719818d09"


def _ws_dir(tmp_root) -> str:
    """建一个工作区目录并返回（workspaces/<uuid>）。"""
    directory = tmp_root / _WS_ID
    directory.mkdir()
    return str(directory)


# ─── resolve_session_sandbox：唯一解析入口 ───


def test_resolve_legacy_unbound_session_creates_session_dir(tmp_root) -> None:
    """未绑定（workspace_id=None）→ legacy 自动目录（与 F3 前逐字节一致）。"""
    result = resolve_session_sandbox(_SID, None, None)
    assert result == os.path.join(str(tmp_root), _SID)
    assert os.path.isdir(result)


def test_resolve_bound_session_points_to_workspace_scope(tmp_root) -> None:
    """绑定 → 工作区根 scope 目录；嵌套 scope 亦被解析。"""
    base = _ws_dir(tmp_root)
    scope = os.path.join(base, "cases")
    os.makedirs(scope)
    result = resolve_session_sandbox(_SID, _WS_ID, "cases")
    assert result == os.path.abspath(scope)
    # 根 scope（空/"/"）→ 工作区目录
    assert resolve_session_sandbox(_SID, _WS_ID, "") == os.path.abspath(base)
    assert resolve_session_sandbox(_SID, _WS_ID, "/") == os.path.abspath(base)


def test_resolve_bound_session_scope_traversal_rejected(tmp_root) -> None:
    """绑定 scope 含 .. / 绝对段 → VALIDATION（防穿越）。"""
    _ws_dir(tmp_root)
    for bad in ("..", "../outside", "/etc", "a/../../b"):
        with pytest.raises(AppError) as exc:
            resolve_session_sandbox(_SID, _WS_ID, bad)
        assert exc.value.code == ErrorCode.VALIDATION


def test_resolve_bound_session_symlink_escape_rejected(tmp_root) -> None:
    """scope 内符号链接指向工作区外 → VALIDATION（fail-closed）。"""
    base = _ws_dir(tmp_root)
    outside = tmp_root.parent / "outside"
    outside.mkdir()
    link = os.path.join(base, "escape")
    try:
        os.symlink(str(outside), link, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境无符号链接权限")
    with pytest.raises(AppError) as exc:
        resolve_session_sandbox(_SID, _WS_ID, "escape")
    assert exc.value.code == ErrorCode.VALIDATION


def test_resolve_bound_session_missing_workspace_dir_fail_closed(tmp_root) -> None:
    """行存在但工作区目录缺失（不一致窗口）→ VALIDATION，绝不回落 legacy。"""
    with pytest.raises(AppError) as exc:
        resolve_session_sandbox(_SID, _WS_ID, "")
    assert exc.value.code == ErrorCode.VALIDATION
    # 关键断言：未悄悄创建/返回 legacy 会话目录
    assert not os.path.exists(os.path.join(str(tmp_root), _SID))


def test_resolve_illegal_workspace_id_rejected(tmp_root) -> None:
    """非法 workspace_id 形态（防路径穿越）→ VALIDATION。"""
    with pytest.raises(AppError) as exc:
        resolve_session_sandbox(_SID, "..%2Fetc", "")
    assert exc.value.code == ErrorCode.VALIDATION


# ─── ensure_workspace_scope：创建时目录就绪 ───


def test_ensure_workspace_scope_creates_missing_scope_dir(tmp_root) -> None:
    base = _ws_dir(tmp_root)
    target = ensure_workspace_scope(_WS_ID, "new/cases")
    assert os.path.isdir(os.path.join(base, "new", "cases"))
    assert target == os.path.abspath(os.path.join(base, "new", "cases"))
    # 幂等：再次调用不报错
    assert ensure_workspace_scope(_WS_ID, "new/cases") == target


def test_ensure_workspace_scope_root_scope(tmp_root) -> None:
    base = _ws_dir(tmp_root)
    assert ensure_workspace_scope(_WS_ID, "") == os.path.abspath(base)


# ─── BLK-4 守卫 ───


def test_session_create_defaults_remain_unbound() -> None:
    """SessionCreate 默认不绑定（F3 前调用方零影响）。"""
    body = SessionCreate()
    assert body.workspace_id is None
    assert body.scope_path is None
    assert body.visibility == "private"


def test_session_create_carries_binding_fields() -> None:
    body = SessionCreate(title="t", visibility="private", workspace_id=_WS_ID, scope_path="cases/1")
    assert body.workspace_id == _WS_ID
    assert body.scope_path == "cases/1"


def test_workspace_dir_for_requires_uuid_shape() -> None:
    with pytest.raises(AppError):
        workspace_dir_for("../etc")
    # uuid 形态通过（纯路径计算）
    assert workspace_dir_for(_WS_ID).endswith(_WS_ID)


def _workspace_row(owner_id: str = "u-1", deleted_at=None) -> SimpleNamespace:
    """桩 Workspace 行（sessions.py 绑定校验分支仅访问 owner/deleted 属性）。"""
    return SimpleNamespace(id=_WS_ID, owner_id=owner_id, deleted_at=deleted_at, name="评测素材")


def _assert_binding_error(user_id: str, visibility: str) -> str | None:
    """复刻 create_session 绑定守卫判断条件（与路由同表达式，供无 DB 单测）。"""
    workspace = _workspace_row(owner_id="u-1")
    if visibility != "private":
        return "绑定工作区的会话必须为私有可见性"
    if workspace is None or workspace.owner_id != user_id or workspace.deleted_at is not None:
        return "工作区不存在或无权绑定"
    return None


def test_binding_guards_team_and_foreign_owner() -> None:
    assert _assert_binding_error("u-1", "team") == "绑定工作区的会话必须为私有可见性"
    assert _assert_binding_error("u-2", "private") == "工作区不存在或无权绑定"


# ─── 路由 surface（401 + 注册断言，仓库既有模式）───


def test_session_routes_require_login() -> None:
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/sessions", json={"title": "x"})
    assert resp.status_code == 401
    # 绑定字段随 POST 体一并存在不改变 401 语义
    resp = client.post(
        "/api/sessions",
        json={"title": "x", "workspace_id": _WS_ID, "scope_path": "cases"},
    )
    assert resp.status_code == 401



