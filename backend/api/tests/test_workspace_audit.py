"""工作区审查回归：分页、文件响应隔离、上传限额与原文件保全。"""

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app import workspace_service
from app.config import settings
from app.errors import AppError, ErrorCode
from app.models import User, Workspace
from app.routers import files, user_workspaces


def test_workspace_pagination_limits_scans_and_keeps_total(monkeypatch):
    """真实 SQL 分页仅扫描当前页；过滤后的 total 不随页大小变化。"""
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    scanned = []
    monkeypatch.setattr(user_workspaces, "_workspace_item", lambda row: scanned.append(row.id) or {"id": row.id})
    with Session(engine) as db:
        for i in range(5):
            db.add(Workspace(id=str(i), name=str(i), owner_id="owner", updated_at=datetime(2026, 9, 19, tzinfo=UTC)))
        db.add(Workspace(id="other", name="other", owner_id="other"))
        db.add(Workspace(id="deleted", name="deleted", owner_id="owner", deleted_at=datetime.now(UTC)))
        db.commit()
        result = user_workspaces.list_workspaces(False, 1, 2, db, SimpleNamespace(id="owner"))
        assert result == {"items": [{"id": "1"}, {"id": "2"}], "total": 5}
        assert scanned == ["1", "2"]
        assert user_workspaces.list_workspaces(False, 10, 2, db, SimpleNamespace(id="owner")) == {"items": [], "total": 5}
    engine.dispose()


def test_workspace_projects_configured_quota(monkeypatch):
    """容量上限由服务端配置投影，前端不得固定为 100MB。"""
    monkeypatch.setattr(settings, "workspace_quota_bytes", 987654321)
    monkeypatch.setattr(user_workspaces, "workspace_dir_for", lambda _: "unused")
    monkeypatch.setattr(user_workspaces, "folder_summary", lambda _: None)
    row = SimpleNamespace(id="workspace", owner_id="owner", name="workspace", created_at=None, updated_at=None, deleted_at=None)
    assert user_workspaces._workspace_item(row)["quota_bytes"] == 987654321


@pytest.mark.parametrize("name", ["page.html", "image.svg", "clip.mp4", "unknown.auditblob"])
def test_raw_workspace_content_is_sandboxed(tmp_path, monkeypatch, name):
    """原始文件不能借平台同源执行脚本，媒体流仍保留 inline。"""
    (tmp_path / name).write_bytes(b"content")
    monkeypatch.setattr(user_workspaces, "_owned_workspace", lambda *a, **k: SimpleNamespace(id="workspace"))
    monkeypatch.setattr(user_workspaces, "workspace_dir_for", lambda _: str(tmp_path))
    response = user_workspaces.get_raw_file("workspace", name, False, Mock(), Mock())
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")
    if name.endswith("auditblob"):
        assert response.media_type == "application/octet-stream"


def test_attachment_content_is_sandboxed(tmp_path, monkeypatch):
    """团队可见 HTML 附件也必须使用隔离响应头。"""
    path = tmp_path / "page.html"
    path.write_text("<script>document.title='unsafe'</script>")
    stored = SimpleNamespace(storage_path=str(path), content_type="text/html", filename=path.name)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = stored
    monkeypatch.setattr(files, "_require_file_access", lambda *a: None)
    response = files.get_file_content("id", db, Mock())
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"


class BoundedUpload(BytesIO):
    """记录读取大小，拒绝退回整文件读取。"""

    def read(self, size=-1):
        assert 0 < size <= 1024 * 1024
        return super().read(size)


def test_upload_stream_does_not_read_whole_file(tmp_path, monkeypatch):
    """通过真实 HTTP 上传验证线程池路由、配额与分块复制接线。"""
    from app.db import get_db
    from app.deps import get_current_user
    from app.main import app

    db = Mock()
    user = SimpleNamespace(id="owner")
    monkeypatch.setattr(user_workspaces, "_owned_workspace", lambda *a, **k: SimpleNamespace(id="workspace"))
    monkeypatch.setattr(user_workspaces, "workspace_dir_for", lambda _: str(tmp_path))
    monkeypatch.setattr(user_workspaces, "write_audit", Mock())
    monkeypatch.setattr(settings, "workspace_quota_bytes", 5 * 1024 * 1024)
    original = UploadFile.read

    async def bounded_read(self, size=-1):
        """旧异步路由不得以 read() 一次性读取上传文件。"""
        assert size > 0
        return await original(self, size)

    monkeypatch.setattr(UploadFile, "read", bounded_read)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/workspaces/workspace/files/upload", files={"file": ("clip.mp4", b"x" * 2_100_000)})
        assert response.status_code == 201, response.text
        assert (tmp_path / "clip.mp4").stat().st_size == 2_100_000
        db.commit.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("failure", ["quota", "read"])
def test_stream_failure_preserves_existing_file(tmp_path, failure):
    """超配额或中途读取失败时原文件完整且不留临时文件。"""
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"original")

    class FailingUpload(BoundedUpload):
        """模拟一次成功读取后上游文件读取失败。"""

        def read(self, size=-1):
            if failure == "read" and self.tell():
                raise OSError("private disk detail")
            return super().read(size)

    with pytest.raises(AppError) as caught:
        workspace_service.save_workspace_file_stream(
            str(tmp_path), "", target.name, FailingUpload(b"x" * 1_100_000),
            max_bytes=10 if failure == "quota" else None,
        )
    assert caught.value.code == (ErrorCode.VALIDATION if failure == "quota" else ErrorCode.INTERNAL)
    assert "private disk detail" not in caught.value.message
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_stream_accepts_exact_limit_in_chunks(tmp_path):
    """刚好达到可用配额的文件正常写入，回传实际大小。"""
    content = b"x" * 1_100_000
    result = workspace_service.save_workspace_file_stream(str(tmp_path), "", "clip.mp4", BoundedUpload(content), max_bytes=len(content))
    assert result["size"] == len(content)
    assert (tmp_path / "clip.mp4").read_bytes() == content


@pytest.mark.parametrize("quota,content,status", [(8, b"new data", 201), (7, b"new data", 400)])
def test_upload_replacement_quota_uses_existing_size(tmp_path, monkeypatch, quota, content, status):
    """覆盖上传只计替换后的容量，超限拒绝且原文件不被截断。"""
    from app.db import get_db
    from app.deps import get_current_user
    from app.main import app

    target = tmp_path / "clip.mp4"
    target.write_bytes(b"old data")
    db = Mock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = SimpleNamespace(id="workspace", owner_id="owner", deleted_at=None)
    monkeypatch.setattr(user_workspaces, "workspace_dir_for", lambda _: str(tmp_path))
    monkeypatch.setattr(user_workspaces, "write_audit", Mock())
    monkeypatch.setattr(settings, "workspace_quota_bytes", quota)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="owner")
    try:
        response = TestClient(app).post("/api/workspaces/workspace/files/upload", files={"file": ("clip.mp4", content)})
        assert response.status_code == status
        assert target.read_bytes() == (content if status == 201 else b"old data")
        db.query.return_value.filter.return_value.with_for_update.assert_called_once()
        if status == 400:
            assert response.json()["code"] == "VALIDATION"
            db.commit.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_sandboxed_media_response_preserves_range(tmp_path, monkeypatch):
    """通过真实 ASGI 文件响应验证隔离头与 206 分段播放可以共存。"""
    from app.db import get_db
    from app.deps import get_current_user
    from app.main import app

    (tmp_path / "clip.mp4").write_bytes(b"0123456789")
    monkeypatch.setattr(user_workspaces, "_owned_workspace", lambda *a, **k: SimpleNamespace(id="workspace"))
    monkeypatch.setattr(user_workspaces, "workspace_dir_for", lambda _: str(tmp_path))
    app.dependency_overrides[get_db] = lambda: Mock()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="owner")
    try:
        response = TestClient(app).get("/api/workspaces/workspace/files/raw?path=clip.mp4", headers={"Range": "bytes=2-5"})
        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert response.headers["content-security-policy"] == "sandbox"
        assert response.headers["content-type"] == "video/mp4"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
