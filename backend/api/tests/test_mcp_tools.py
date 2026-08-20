"""内部短 MCP 工具：取消、用例确认、未启用能力不假成功。"""

from app.agent.defaults import IMPLEMENTED_SHORT_TOOLS, MCP_TOOL_ORDER, SHORT_TOOLS
from app.agent.mcp_tools import execute_short_tool
from app.models import CaseSet, Task
from app.routers.mcp import builtin_tools


class _CancelQuery:
    """覆盖 filter / with_for_update / first 的最小查询桩。"""

    def __init__(self, task: Task | None):
        self.task = task
        self.locked = False

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def first(self):
        return self.task


class _CancelDb:
    def __init__(self, task: Task | None):
        self.query_result = _CancelQuery(task)
        self.added: list = []

    def query(self, *_args, **_kwargs):
        return self.query_result

    def add(self, item):
        self.added.append(item)


def _running_task(*, creator: str = "u1", session_id: str = "s1") -> Task:
    return Task(
        id="t-1",
        kind="benchmark",
        status="running",
        session_id=session_id,
        created_by=creator,
        config={},
        progress={"done": 1, "total": 10},
        result={},
    )


def test_inventory_enabled_matches_implementation():
    """GET /api/mcp/tools 的 enabled 不得把 kb.list 标成已落地。"""
    items = {item.name: item for item in builtin_tools()}
    assert set(items) == set(MCP_TOOL_ORDER) == set(SHORT_TOOLS)
    assert items["task.cancel"].enabled is True
    assert items["testcase.confirm"].enabled is True
    assert items["kb.list"].enabled is False
    assert items["kb.list"].permission == "read"
    assert items["testcase.confirm"].permission == "write"
    assert "kb.list" not in IMPLEMENTED_SHORT_TOOLS


def test_kb_list_does_not_fake_success():
    ok, data, error, _latency = execute_short_tool(
        _CancelDb(None), "kb.list", {}, user_id="u1"
    )
    assert ok is False
    assert data is None
    assert error == "该能力未启用"


def test_task_cancel_by_owner_updates_status():
    task = _running_task()
    db = _CancelDb(task)
    ok, data, error, _latency = execute_short_tool(
        db, "task.cancel", {"task_id": task.id}, user_id="u1", session_id="s1"
    )
    assert ok is True
    assert error is None
    assert data["ok"] is True
    assert data["task_id"] == "t-1"
    assert task.status == "cancelled"
    assert task.cancel_requested_at == task.finished_at
    assert db.query_result.locked is True
    assert {type(item).__name__ for item in db.added} >= {"TaskEvent", "AuditLog"}


def test_task_cancel_rejects_other_user():
    task = _running_task(creator="owner")
    ok, _data, error, _latency = execute_short_tool(
        _CancelDb(task), "task.cancel", {"task_id": task.id}, user_id="other"
    )
    assert ok is False
    assert error == "没有权限做这件事"
    assert task.status == "running"


def test_task_cancel_rejects_other_session():
    task = _running_task(session_id="s-other")
    ok, _data, error, _latency = execute_short_tool(
        _CancelDb(task),
        "task.cancel",
        {"task_id": task.id},
        user_id="u1",
        session_id="s1",
    )
    assert ok is False
    assert error == "只能取消当前会话中的任务"
    assert task.status == "running"


class _CaseQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class _CaseDb:
    """按查询模型返回用例集或关联任务。"""

    def __init__(self, case_set: CaseSet, task: Task | None = None):
        self.case_set = case_set
        self.task = task
        self.added: list = []

    def query(self, model):
        if model is CaseSet:
            return _CaseQuery(self.case_set)
        return _CaseQuery(self.task)

    def add(self, item):
        self.added.append(item)


def test_testcase_confirm_succeeds_and_links_task():
    case_set = CaseSet(
        id="cs-1",
        name="smoke",
        status="generated",
        generated_count=3,
        confirmed_count=0,
        created_by="u1",
        task_id="t-case",
    )
    task = Task(
        id="t-case",
        kind="testcase",
        status="awaiting_case_confirm",
        created_by="u1",
        config={},
        progress={},
        result={},
    )
    ok, data, error, _latency = execute_short_tool(
        _CaseDb(case_set, task),
        "testcase.confirm",
        {"case_set_id": "cs-1"},
        user_id="u1",
    )
    assert ok is True
    assert error is None
    assert data["status"] == "succeeded"
    assert data["case_set_id"] == "cs-1"
    assert case_set.status == "confirmed"
    assert case_set.confirmed_count == 3
    assert task.status == "succeeded"
    assert task.finished_at is not None


def test_testcase_confirm_requires_case_set_id():
    ok, _data, error, _latency = execute_short_tool(
        _CaseDb(CaseSet(id="cs-1", name="smoke", status="generated", created_by="u1")),
        "testcase.confirm",
        {},
        user_id="u1",
    )
    assert ok is False
    assert error == "case_set_id 必填"


def test_testcase_confirm_rejects_terminal_set():
    case_set = CaseSet(id="cs-1", name="done", status="confirmed", created_by="u1")
    ok, _data, error, _latency = execute_short_tool(
        _CaseDb(case_set),
        "testcase.confirm",
        {"case_set_id": "cs-1"},
        user_id="u1",
    )
    assert ok is False
    assert error == "用例集已终态，请勿重复操作"
