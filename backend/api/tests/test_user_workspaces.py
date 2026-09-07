"""用户工作区 F1 单测：service 路径安全纯函数 + 路由未登录鉴权；不依赖数据库。

覆盖设计稿 A V0.4.1 §4 的守卫面：
- 目录名/相对路径段级校验（``.``/``..``/分隔符/超长）；
- 逐段 realpath 前缀重验与符号链接逃逸拒绝（resolve→browse 窗口静态面）；
- 孤儿候选按受保护集合过滤（行态区分由路由侧组装，service 侧纯输入）；
- 路由层未登录 401（与 admin 工作区测试同构）。
"""

import os

import pytest
from fastapi.testclient import TestClient

from app import workspace_service
from app.main import app
from app.routers import user_workspaces
from app.routers.workspaces import _match_session  # noqa: F401  确保 admin 模块导入链


class TestValidateSegment:
    """单段目录名校验（新建文件夹 / 孤儿清理共用）。"""

    def test_accepts_normal_name(self) -> None:
        assert workspace_service.validate_segment("我的素材") == "我的素材"
        assert workspace_service.validate_segment("data-v2") == "data-v2"

    def test_rejects_dot_and_dotdot(self) -> None:
        for bad in ("", ".", ".."):
            with pytest.raises(Exception):
                workspace_service.validate_segment(bad)

    def test_rejects_separators_and_too_long(self) -> None:
        for bad in ("a/b", "a\\b", "x" * 256):
            with pytest.raises(Exception):
                workspace_service.validate_segment(bad)


class TestResolveScopeDir:
    """相对 scope 解析：穿越/符号链接逃逸拒绝（设计稿 §5 resolve 校验链）。"""

    def test_empty_scope_returns_base(self, tmp_path) -> None:
        base = str(tmp_path)
        assert workspace_service.resolve_scope_dir(base, "") == base
        assert workspace_service.resolve_scope_dir(base, "/") == base

    def test_nested_scope_resolves(self, tmp_path) -> None:
        base = str(tmp_path)
        os.makedirs(os.path.join(base, "a", "b"))
        target = workspace_service.resolve_scope_dir(base, "a/b")
        assert target == os.path.join(base, "a", "b")

    def test_nonexistent_leaf_allowed(self, tmp_path) -> None:
        # 尚不存在的段（将由其后的 mkdir 创建）仅做名字校验
        base = str(tmp_path)
        target = workspace_service.resolve_scope_dir(base, "new/child")
        assert target == os.path.join(base, "new", "child")

    def test_dotdot_rejected(self, tmp_path) -> None:
        base = str(tmp_path)
        with pytest.raises(Exception):
            workspace_service.resolve_scope_dir(base, "..")

    def test_symlink_escape_rejected(self, tmp_path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        link = tmp_path / "link"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(Exception):
            workspace_service.resolve_scope_dir(str(tmp_path), "link")
        with pytest.raises(Exception):
            workspace_service.resolve_scope_dir(str(tmp_path), "link/sub")

    def test_missing_base_rejected(self, tmp_path) -> None:
        with pytest.raises(Exception):
            workspace_service.resolve_scope_dir(str(tmp_path / "absent"), "")


class TestDirLevel:
    """一层目录列表：目录/文件/链接分类与排序，不递归不跟随链接。"""

    def test_lists_one_level_sorted_dirs_first(self, tmp_path) -> None:
        base = str(tmp_path)
        os.makedirs(os.path.join(base, "b_dir"))
        (tmp_path / "a_file.txt").write_text("x", encoding="utf-8")
        entries = workspace_service.list_dir_level(base)
        names = [entry["name"] for entry in entries]
        assert names == ["b_dir", "a_file.txt"]  # 目录在前
        assert entries[0]["kind"] == "dir"
        assert entries[1]["kind"] == "file"
        assert entries[1]["size"] == 1

    def test_symlink_exposed_without_follow(self, tmp_path) -> None:
        base = str(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "lnk").symlink_to(outside, target_is_directory=True)
        entries = workspace_service.list_dir_level(base)
        link = next(entry for entry in entries if entry["name"] == "lnk")
        assert link["kind"] == "link"

    def test_missing_dir_raises_not_found(self, tmp_path) -> None:
        with pytest.raises(Exception):
            workspace_service.list_dir_level(str(tmp_path / "absent"))


class TestCreateChildDir:
    """新建文件夹：单段名校验、幂等、同名链接拒绝。"""

    def test_create_and_idempotent(self, tmp_path) -> None:
        base = str(tmp_path)
        target = workspace_service.create_child_dir(base, "素材")
        assert os.path.isdir(target)
        # 幂等：已存在同名目录直接返回
        again = workspace_service.create_child_dir(base, "素材")
        assert again == target

    def test_rejects_same_name_symlink(self, tmp_path) -> None:
        base = str(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "lnk").symlink_to(outside, target_is_directory=True)
        with pytest.raises(Exception):
            workspace_service.create_child_dir(base, "lnk")

    def test_rejects_bad_name(self, tmp_path) -> None:
        with pytest.raises(Exception):
            workspace_service.create_child_dir(str(tmp_path), "../x")


class TestOrphanChildren:
    """孤儿候选过滤：受保护 id（会话 ∪ 活跃工作区）不进候选。"""

    def test_filters_protected_and_non_dirs(self, tmp_path) -> None:
        root = str(tmp_path)
        protected = {"834a68f1-a4fd-4261-8677-6f51830c895d"}
        os.makedirs(os.path.join(root, "834a68f1-a4fd-4261-8677-6f51830c895d"))
        os.makedirs(os.path.join(root, "leftover"))
        (tmp_path / "note.txt").write_text("x", encoding="utf-8")
        assert workspace_service.orphan_direct_children(root, protected) == ["leftover"]

    def test_empty_root(self, tmp_path) -> None:
        assert workspace_service.orphan_direct_children(str(tmp_path), set()) == []


class TestUserRouterAuth:
    """用户域工作区路由未登录鉴权（与 admin 测试同构，不依赖数据库）。"""

    @pytest.fixture()
    def client(self) -> TestClient:
        return TestClient(app)

    def test_list_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/workspaces")
        assert resp.status_code == 401
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_create_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/api/workspaces", json={"name": "素材库"})
        assert resp.status_code == 401

    def test_rename_requires_auth(self, client: TestClient) -> None:
        resp = client.put("/api/workspaces/some-id", json={"name": "x"})
        assert resp.status_code == 401

    def test_delete_requires_auth(self, client: TestClient) -> None:
        resp = client.delete("/api/workspaces/some-id")
        assert resp.status_code == 401

    def test_purge_requires_auth(self, client: TestClient) -> None:
        resp = client.delete("/api/workspaces/some-id?purge=true")
        assert resp.status_code == 401

    def test_files_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/workspaces/some-id/files")
        assert resp.status_code == 401

    def test_folder_create_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/api/workspaces/some-id/files", json={"path": "", "name": "d"})
        assert resp.status_code == 401


def test_router_module_surface() -> None:
    """路由注册面：模块可导入且暴露 router（回归锁）。"""
    assert user_workspaces.router.prefix == "/api/workspaces"
    # 目录名与 id 形态：服务层校验拒绝非法标识
    with pytest.raises(Exception):
        workspace_service.workspace_dir_for("../etc")
    with pytest.raises(Exception):
        workspace_service.workspace_dir_for("")
