"""用户工作区文件操作单测：读写、新建、重命名、删除与防穿越安全校验。"""

import os

import pytest

from app import workspace_service
from app.errors import AppError


class TestWorkspaceFileOperations:
    def test_create_and_read_text_file(self, tmp_path) -> None:
        base = str(tmp_path)
        # 创建文件
        created = workspace_service.create_workspace_file(
            base, "", "test.py", "print('hello world')\n"
        )
        assert created["name"] == "test.py"
        assert created["path"] == "test.py"
        assert created["size"] > 0

        # 读取文件
        res = workspace_service.read_workspace_file(base, "test.py")
        assert res["name"] == "test.py"
        assert res["content"] == "print('hello world')\n"
        assert res["is_binary"] is False
        assert res["is_large"] is False

    def test_update_file_content(self, tmp_path) -> None:
        base = str(tmp_path)
        workspace_service.create_workspace_file(base, "", "doc.md", "# Title")
        updated = workspace_service.write_workspace_file(base, "doc.md", "# New Title\nContent")
        assert updated["path"] == "doc.md"

        res = workspace_service.read_workspace_file(base, "doc.md")
        assert res["content"] == "# New Title\nContent"

    def test_binary_file_detection(self, tmp_path) -> None:
        base = str(tmp_path)
        bin_path = os.path.join(base, "image.png")
        with open(bin_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        res = workspace_service.read_workspace_file(base, "image.png")
        assert res["is_binary"] is True
        assert res["content"] == ""

    def test_nested_file_creation(self, tmp_path) -> None:
        base = str(tmp_path)
        os.makedirs(os.path.join(base, "subdir"))
        created = workspace_service.create_workspace_file(
            base, "subdir", "sub.txt", "sub content"
        )
        assert created["path"] == "subdir/sub.txt"
        res = workspace_service.read_workspace_file(base, "subdir/sub.txt")
        assert res["content"] == "sub content"

    def test_rename_file(self, tmp_path) -> None:
        base = str(tmp_path)
        workspace_service.create_workspace_file(base, "", "old.txt", "content")
        res = workspace_service.rename_workspace_path(base, "old.txt", "new.txt")
        assert res["old_path"] == "old.txt"
        assert res["new_path"] == "new.txt"
        assert not os.path.exists(os.path.join(base, "old.txt"))
        assert os.path.exists(os.path.join(base, "new.txt"))

    def test_rename_directory(self, tmp_path) -> None:
        base = str(tmp_path)
        os.makedirs(os.path.join(base, "folder_a"))
        res = workspace_service.rename_workspace_path(base, "folder_a", "folder_b")
        assert res["new_path"] == "folder_b"
        assert not os.path.exists(os.path.join(base, "folder_a"))
        assert os.path.exists(os.path.join(base, "folder_b"))

    def test_delete_file_and_directory(self, tmp_path) -> None:
        base = str(tmp_path)
        # 删除文件
        workspace_service.create_workspace_file(base, "", "to_delete.txt", "xxx")
        res = workspace_service.delete_workspace_path(base, "to_delete.txt")
        assert res["deleted"] is True
        assert not os.path.exists(os.path.join(base, "to_delete.txt"))

        # 删除目录
        os.makedirs(os.path.join(base, "dir_to_del", "nested"))
        with open(os.path.join(base, "dir_to_del", "nested", "f.txt"), "w") as f:
            f.write("nested")
        res_dir = workspace_service.delete_workspace_path(base, "dir_to_del")
        assert res_dir["deleted"] is True
        assert not os.path.exists(os.path.join(base, "dir_to_del"))

    def test_prevent_root_deletion(self, tmp_path) -> None:
        base = str(tmp_path)
        with pytest.raises(AppError):
            workspace_service.delete_workspace_path(base, "")
        with pytest.raises(AppError):
            workspace_service.delete_workspace_path(base, "/")

    def test_path_traversal_prevention(self, tmp_path) -> None:
        base = str(tmp_path)
        for evil in ("../outside.txt", "/etc/passwd", "a/../../outside"):
            with pytest.raises(AppError):
                workspace_service.read_workspace_file(base, evil)
            with pytest.raises(AppError):
                workspace_service.delete_workspace_path(base, evil)
            with pytest.raises(AppError):
                workspace_service.rename_workspace_path(base, evil, "hack.txt")

    def test_get_file_tree(self, tmp_path) -> None:
        base = str(tmp_path)
        os.makedirs(os.path.join(base, "pkg"))
        with open(os.path.join(base, "root.txt"), "w") as f:
            f.write("root")
        with open(os.path.join(base, "pkg", "inner.py"), "w") as f:
            f.write("inner")

        tree = workspace_service.get_file_tree(base)
        assert len(tree) == 2
        # 目录排在前
        dir_node = next(n for n in tree if n["kind"] == "dir")
        file_node = next(n for n in tree if n["kind"] == "file")
        assert dir_node["name"] == "pkg"
        assert len(dir_node["children"]) == 1
        assert dir_node["children"][0]["name"] == "inner.py"
        assert file_node["name"] == "root.txt"

    def test_save_workspace_file_bytes(self, tmp_path) -> None:
        base = str(tmp_path)
        # 保存二进制视频内容
        video_bytes = b"\x00\x00\x00 ftypisom\x00\x00\x02\x00"
        res = workspace_service.save_workspace_file_bytes(base, "", "sample.mp4", video_bytes)
        assert res["name"] == "sample.mp4"
        assert res["path"] == "sample.mp4"
        assert res["size"] == len(video_bytes)

        # 嵌套目录保存
        os.makedirs(os.path.join(base, "media"))
        audio_bytes = b"ID3\x03\x00\x00\x00"
        res_sub = workspace_service.save_workspace_file_bytes(base, "media", "bgm.mp3", audio_bytes)
        assert res_sub["path"] == "media/bgm.mp3"
        assert res_sub["size"] == len(audio_bytes)

        # 拒绝非法名字
        with pytest.raises(AppError):
            workspace_service.save_workspace_file_bytes(base, "", "../evil.mp4", b"bad")
