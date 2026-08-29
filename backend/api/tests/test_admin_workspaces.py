"""管理端工作区接口单测：分页过滤纯函数 + 未登录鉴权；不依赖数据库连接。"""

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.routers.workspaces import _match_session, _paginate_entries


def _entry(
    title: str | None = None,
    owner: str | None = None,
    session_id: str = "834a68f1-a4fd-4261-8677-6f51830c895d",
    has_folder: bool = False,
    is_deleted: bool = False,
) -> tuple[str | None, str | None, str, bool, bool]:
    """构造 ``_match_session`` 接受的五元组。"""
    return (title, owner, session_id, has_folder, is_deleted)


class TestMatchSession:
    """过滤判定：关键词 / 文件夹 / 删除状态。"""

    def test_keyword_matches_title_owner_and_id(self) -> None:
        # 关键词对标题 / 归属 / 会话 ID 任一命中即通过（大小写不敏感）
        assert _match_session(_entry(title="压测会话"), "压测", "all", "all")
        assert _match_session(_entry(owner="Alice"), "alice", "all", "all")
        assert _match_session(_entry(session_id="834a-XYZ"), "834a-xyz", "all", "all")

    def test_keyword_miss(self) -> None:
        # 三者均未命中则过滤掉
        assert not _match_session(_entry(title="基准评测"), "不存在词", "all", "all")

    def test_folder_filter(self) -> None:
        # has/none 与磁盘是否有目录一一对应
        assert _match_session(_entry(has_folder=True), "", "has", "all")
        assert not _match_session(_entry(has_folder=False), "", "has", "all")
        assert _match_session(_entry(has_folder=False), "", "none", "all")
        assert not _match_session(_entry(has_folder=True), "", "none", "all")

    def test_deleted_filter(self) -> None:
        # active 只保留正常会话，deleted 只保留软删除会话
        assert _match_session(_entry(is_deleted=False), "", "all", "active")
        assert not _match_session(_entry(is_deleted=True), "", "all", "active")
        assert _match_session(_entry(is_deleted=True), "", "all", "deleted")
        assert not _match_session(_entry(is_deleted=False), "", "all", "deleted")

    def test_combined_filters(self) -> None:
        # 组合条件需同时满足
        entry = _entry(title="报告", has_folder=True, is_deleted=False)
        assert _match_session(entry, "报告", "has", "active")
        assert not _match_session(entry, "报告", "none", "active")


class TestPaginateEntries:
    """排序切片：updated_at 倒序、缺失置底、offset/limit 切片与总数。"""

    @staticmethod
    def _row(session_id: str, updated_at: datetime | None):
        # 构造 _paginate_entries 接受的 (会话对象, 归属) 二元组
        return SimpleNamespace(id=session_id, updated_at=updated_at), None

    def test_orders_by_updated_at_desc_and_slices(self) -> None:
        rows = [
            self._row("a", datetime(2026, 8, 1, tzinfo=UTC)),
            self._row("b", datetime(2026, 8, 3, tzinfo=UTC)),
            self._row("c", datetime(2026, 8, 2, tzinfo=UTC)),
        ]
        page, total = _paginate_entries(rows, offset=0, limit=2)
        assert total == 3
        assert [row[0].id for row in page] == ["b", "c"]
        page2, _total = _paginate_entries(rows, offset=2, limit=2)
        assert [row[0].id for row in page2] == ["a"]

    def test_missing_updated_at_sorts_last(self) -> None:
        # updated_at 缺失视为 0，排在最后且不参与时间比较异常
        rows = [
            self._row("a", None),
            self._row("b", datetime(2026, 8, 3, tzinfo=UTC)),
        ]
        page, total = _paginate_entries(rows, offset=0, limit=10)
        assert total == 2
        assert [row[0].id for row in page] == ["b", "a"]

    def test_offset_beyond_total_returns_empty(self) -> None:
        page, total = _paginate_entries([], offset=50, limit=50)
        assert page == []
        assert total == 0


def test_list_workspaces_requires_auth() -> None:
    # 未登录访问分页列表应统一 401 + UNAUTHORIZED
    client = TestClient(app)
    resp = client.get("/api/admin/workspaces")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_workspace_stats_requires_auth() -> None:
    # 未登录访问磁盘统计端点同样 401
    client = TestClient(app)
    resp = client.get("/api/admin/workspaces/stats")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"
