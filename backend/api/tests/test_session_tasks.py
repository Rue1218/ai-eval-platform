"""会话看板 Task 四件套与 ask_user_question 单测。"""

from app.errors import AppError
from app.harness.execution.aliases import normalize_tool_arguments
from app.harness.execution.ask_user import answers_from_reply, validate_questions
from app.harness.execution.registry import build_default_registry
from app.harness.execution.session_board import (
    create_task,
    get_task,
    import_plan_steps,
    list_tasks,
    replace_plan_steps,
    update_task,
)


def test_task_create_returns_nested_task_id() -> None:
    """创建项必须返回 task.id，而不是评测入队的 task_id。"""
    board: list[dict] = []
    item = create_task(board, {"subject": "拆解评测", "description": "先选数据集"})
    assert item["id"].startswith("task_")
    assert item["task"]["id"] == item["id"]
    assert item["task"]["subject"] == "拆解评测"
    assert get_task(board, item["id"])["task"]["description"] == "先选数据集"


def test_task_get_missing_returns_none() -> None:
    assert get_task([], "task_missing") is None


def test_task_update_assigns_owner_when_in_progress() -> None:
    board: list[dict] = []
    item = create_task(board, {"subject": "写报告"})
    updated = update_task(
        board,
        {"taskId": item["id"], "status": "in_progress"},
        owner="user-1",
    )
    assert updated["task"]["status"] == "in_progress"
    assert updated["task"]["owner"] == "user-1"


def test_task_update_deleted_hidden_from_list() -> None:
    board: list[dict] = []
    item = create_task(board, {"subject": "临时项"})
    update_task(board, {"taskId": item["id"], "status": "deleted"})
    assert list_tasks(board) == []
    assert get_task(board, item["id"]) is None
    try:
        update_task(board, {"taskId": item["id"], "status": "pending"})
    except AppError as exc:
        assert exc.code.value == "NOT_FOUND"
    else:
        raise AssertionError("已删除项不应被复活")


def test_task_update_respects_blocked_by() -> None:
    board: list[dict] = []
    first = create_task(board, {"subject": "前置"})
    second = create_task(board, {"subject": "后置"})
    try:
        update_task(
            board,
            {"taskId": second["id"], "status": "in_progress", "addBlockedBy": [first["id"]]},
        )
    except AppError as exc:
        assert exc.code.value == "VALIDATION"
    else:
        raise AssertionError("未完成前置任务时应拒绝推进")


def test_task_aliases_normalize_task_id() -> None:
    schema = build_default_registry().get("TaskGet").parameters_schema
    out = normalize_tool_arguments("TaskGet", {"id": "task_abc"}, schema)
    assert out["taskId"] == "task_abc"
    assert "id" not in out


def test_task_create_alias_subject() -> None:
    schema = build_default_registry().get("TaskCreate").parameters_schema
    out = normalize_tool_arguments("TaskCreate", {"title": "只给了旧名"}, schema)
    assert out["subject"] == "只给了旧名"


def test_import_plan_steps_writes_parent_and_children() -> None:
    board: list[dict] = []
    created = import_plan_steps(
        board,
        subject="评测清单",
        description="完整指令",
        steps=[{"title": "选数据集", "status": "pending"}, {"title": "确认卡", "status": "completed"}],
    )
    assert len(created) == 3
    assert [item["task"]["status"] for item in list_tasks(board)] == [
        "pending",
        "pending",
        "completed",
    ]


def test_import_plan_steps_rejects_over_capacity() -> None:
    board: list[dict] = []
    steps = [{"title": f"步骤{index}"} for index in range(32)]
    try:
        import_plan_steps(board, subject="父项", description="完整指令", steps=steps)
    except AppError as exc:
        assert exc.code.value == "VALIDATION"
    else:
        raise AssertionError("超容量应整批拒绝")
    assert board == []


def test_replace_plan_steps_only_replaces_native_plan_entries() -> None:
    """原生 task 整表更新不能删除 TaskCreate 等看板条目。"""
    board: list[dict] = []
    manual = create_task(board, {"subject": "人工看板项"})
    replace_plan_steps(
        board,
        subject="首次规划",
        description="排查并修复问题",
        steps=[{"title": "定位", "status": "in_progress"}],
    )
    replace_plan_steps(
        board,
        subject="更新规划",
        description="排查并修复问题",
        steps=[{"title": "修复", "status": "completed"}],
    )

    visible = list_tasks(board)
    assert len(visible) == 3
    assert visible[0]["id"] == manual["id"]
    assert visible[0]["task"]["subject"] == "人工看板项"
    assert visible[1]["task"]["metadata"]["source"] == "task.plan"
    assert visible[2]["task"]["subject"] == "修复"
    assert visible[2]["task"]["status"] == "completed"


def test_ask_user_question_validates_and_projects_answers() -> None:
    questions = validate_questions(
        {
            "questions": [
                {
                    "id": "dataset",
                    "question": "用哪个数据集？",
                    "options": [{"label": "MMLU", "description": "推荐"}],
                }
            ]
        }
    )
    answers = answers_from_reply(questions, "MMLU")
    assert answers == [{"id": "dataset", "selected": ["MMLU"], "custom": "MMLU"}]


def test_ask_user_question_keeps_blank_lines_and_splits_multi() -> None:
    questions = validate_questions(
        {
            "questions": [
                {"id": "optional", "question": "可跳过", "required": False},
                {
                    "id": "dataset",
                    "question": "用哪个数据集？",
                    "multi_select": True,
                    "options": [{"label": "MMLU"}, {"label": "C-Eval"}],
                },
            ]
        }
    )
    answers = answers_from_reply(questions, "\nMMLU, C-Eval")
    assert answers[0] == {"id": "optional", "selected": [], "custom": ""}
    assert answers[1] == {
        "id": "dataset",
        "selected": ["MMLU", "C-Eval"],
        "custom": "MMLU, C-Eval",
    }


def test_ask_user_question_rejects_empty() -> None:
    try:
        validate_questions({"questions": []})
    except AppError as exc:
        assert exc.code.value == "VALIDATION"
    else:
        raise AssertionError("应拒绝空 questions")


def test_registry_has_session_task_tools_not_colliding_with_queue() -> None:
    registry = build_default_registry()
    assert registry.get("TaskCreate").transport == "native"
    assert registry.get("task.create").transport == "mcp"
