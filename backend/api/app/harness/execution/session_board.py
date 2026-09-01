"""会话内任务看板：TaskCreate / TaskGet / TaskUpdate / TaskList。

这是对话拆解清单，不是评测入队（``task.create``）也不是多 Agent 子进程。
状态只存在于当前图的 ``GraphState.session_tasks``，不写 PG ``tasks`` 表。
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from app.errors import AppError, ErrorCode

_STATUSES = frozenset({"pending", "in_progress", "completed", "deleted"})
_MAX_TASKS = 32
_MAX_SUBJECT = 120
_MAX_DESCRIPTION = 2000


def _as_record(value: object) -> dict[str, object]:
    """把看板项投影为可序列化字典。"""
    return dict(value) if isinstance(value, Mapping) else {}


def snapshot_board(raw: object) -> list[dict[str, object]]:
    """从 GraphState 取出看板副本；非法项丢弃。"""
    if not isinstance(raw, list):
        return []
    items: list[dict[str, object]] = []
    for item in raw:
        rec = _as_record(item)
        task_id = str(rec.get("id") or "").strip()
        subject = str(rec.get("subject") or "").strip()
        if task_id and subject:
            items.append(dict(rec))
    return items


def public_task(item: Mapping[str, object]) -> dict[str, object]:
    """对外投影：嵌套 ``task.id``，并带扁平 id / status。"""
    task_id = str(item.get("id") or "")
    return {
        "id": task_id,
        "status": str(item.get("status") or "pending"),
        "task": {
            "id": task_id,
            "subject": str(item.get("subject") or ""),
            "description": str(item.get("description") or ""),
            "activeForm": str(item.get("activeForm") or ""),
            "status": str(item.get("status") or "pending"),
            "owner": str(item.get("owner") or ""),
            "metadata": item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {},
            "addBlocks": list(item.get("addBlocks") or []),
            "addBlockedBy": list(item.get("addBlockedBy") or []),
        },
    }


def create_task(
    board: list[dict[str, object]],
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """创建看板项；返回含 ``task.id`` 的安全投影。"""
    visible = [item for item in board if str(item.get("status") or "") != "deleted"]
    if len(visible) >= _MAX_TASKS:
        raise AppError(ErrorCode.VALIDATION, f"会话任务清单最多 {_MAX_TASKS} 项")
    subject = str(arguments.get("subject") or "").strip()
    if not subject or len(subject) > _MAX_SUBJECT:
        raise AppError(ErrorCode.VALIDATION, "subject 不能为空且不超过 120 字")
    description = str(arguments.get("description") or "").strip()
    if len(description) > _MAX_DESCRIPTION:
        raise AppError(ErrorCode.VALIDATION, "description 过长")
    item = {
        "id": f"task_{uuid4().hex[:12]}",
        "subject": subject,
        "description": description,
        "activeForm": str(arguments.get("activeForm") or "").strip(),
        "status": "pending",
        "owner": "",
        "metadata": dict(arguments.get("metadata") or {})
        if isinstance(arguments.get("metadata"), Mapping)
        else {},
        "addBlocks": [],
        "addBlockedBy": [],
    }
    board.append(item)
    return public_task(item)


def get_task(board: list[dict[str, object]], task_id: str) -> dict[str, object] | None:
    """按 id 取完整项；找不到或已删除返回 None。"""
    wanted = str(task_id or "").strip()
    if not wanted:
        raise AppError(ErrorCode.VALIDATION, "taskId 不能为空")
    for item in board:
        if str(item.get("id") or "") == wanted and str(item.get("status") or "") != "deleted":
            return public_task(item)
    return None


def update_task(
    board: list[dict[str, object]],
    arguments: Mapping[str, object],
    *,
    owner: str = "",
) -> dict[str, object]:
    """更新看板项；``in_progress`` 且未指定 owner 时写入当前用户。"""
    task_id = str(arguments.get("taskId") or "").strip()
    status = str(arguments.get("status") or "").strip()
    if status not in _STATUSES:
        raise AppError(ErrorCode.VALIDATION, "status 必须是 pending/in_progress/completed/deleted")
    target: dict[str, object] | None = None
    for item in board:
        if str(item.get("id") or "") == task_id:
            target = item
            break
    if target is None or str(target.get("status") or "") == "deleted":
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在")
    blocker_ids = {str(item).strip() for item in (target.get("addBlockedBy") or []) if str(item).strip()}
    incoming_blockers = arguments.get("addBlockedBy")
    if isinstance(incoming_blockers, list):
        blocker_ids.update(str(item).strip() for item in incoming_blockers if str(item).strip())
    if status in {"in_progress", "completed"}:
        by_id = {str(item.get("id") or ""): item for item in board}
        for blocker_id in blocker_ids:
            other = by_id.get(blocker_id)
            if other is None or str(other.get("status") or "") not in {"completed", "deleted"}:
                raise AppError(ErrorCode.VALIDATION, "存在未完成的前置任务")
        target_id = str(target.get("id") or "")
        for item in board:
            if item is target:
                continue
            blocks = {str(value).strip() for value in (item.get("addBlocks") or []) if str(value).strip()}
            if target_id in blocks and str(item.get("status") or "") not in {"completed", "deleted"}:
                raise AppError(ErrorCode.VALIDATION, "存在未完成的前置任务")
    target["status"] = status
    for key in ("subject", "description", "activeForm"):
        if key in arguments and arguments.get(key) not in (None, ""):
            text = str(arguments.get(key) or "").strip()
            if key == "subject" and (not text or len(text) > _MAX_SUBJECT):
                raise AppError(ErrorCode.VALIDATION, "subject 不能为空且不超过 120 字")
            target[key] = text
    if arguments.get("owner"):
        target["owner"] = str(arguments.get("owner") or "").strip()
    elif status == "in_progress" and not str(target.get("owner") or "").strip():
        target["owner"] = str(owner or "").strip()
    if isinstance(arguments.get("metadata"), Mapping):
        meta = dict(target.get("metadata") or {}) if isinstance(target.get("metadata"), Mapping) else {}
        meta.update(dict(arguments["metadata"]))
        target["metadata"] = meta
    for key in ("addBlocks", "addBlockedBy"):
        extra = arguments.get(key)
        if isinstance(extra, list) and extra:
            current = [str(item) for item in (target.get(key) or [])]
            current.extend(str(item) for item in extra if str(item).strip())
            target[key] = current
    return public_task(target)


def board_tool_data(summary: str, display: Mapping[str, object], model_text: str = "") -> dict[str, object]:
    """统一看板工具的 Observation / ToolCard 投影。"""
    payload = dict(display)
    payload.setdefault("summary", summary)
    return {
        "summary": summary,
        "model_text": model_text or summary,
        "source": "session:task-board",
        "display": payload,
    }


class BoardToolResult:
    """供 execute_raw 识别的看板工具结果。"""

    def __init__(self, summary: str, display: Mapping[str, object], model_text: str = "") -> None:
        self._data = board_tool_data(summary, display, model_text)

    def to_tool_data(self) -> dict[str, object]:
        """返回模型摘要与安全 display。"""
        return dict(self._data)


def list_tasks(board: list[dict[str, object]]) -> list[dict[str, object]]:
    """返回未删除任务快照。"""
    return [
        public_task(item)
        for item in board
        if str(item.get("status") or "") != "deleted"
    ]


def import_plan_steps(
    board: list[dict[str, object]],
    *,
    subject: str,
    description: str,
    steps: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    """把旧 ``task`` 清单写入看板：父项 + 每步一项。"""
    titles = [str(step.get("title") or "").strip() for step in steps]
    needed = 1 + sum(1 for title in titles if title)
    visible = sum(1 for item in board if str(item.get("status") or "") != "deleted")
    if visible + needed > _MAX_TASKS:
        raise AppError(ErrorCode.VALIDATION, f"会话任务清单最多 {_MAX_TASKS} 项")
    created: list[dict[str, object]] = []
    parent = create_task(
        board,
        {"subject": subject, "description": description, "activeForm": "拆解任务"},
    )
    created.append(parent)
    parent_id = str(parent.get("id") or "")
    for step in steps:
        title = str(step.get("title") or "").strip()
        if not title:
            continue
        child = create_task(
            board,
            {
                "subject": title[:_MAX_SUBJECT],
                "description": title,
                "activeForm": title,
                "metadata": {"parent": parent_id},
            },
        )
        status = str(step.get("status") or "pending")
        if status in {"in_progress", "completed"}:
            child = update_task(
                board,
                {"taskId": child["id"], "status": status},
            )
        created.append(child)
    return created
