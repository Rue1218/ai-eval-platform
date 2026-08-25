"""Harness 执行层：长任务入队桥接（M5，EX-4）。

``enqueue_long_task`` 创建 ``queued`` Task + AuditLog 交 Worker 消费，
**不阻塞对话回合**（入队即返回 task_id，进度/报告/错误由 Worker 写
``ws_events``）。``kind`` 取 Task.kind 短名（benchmark/testcase/rag/stress），
与 M10 ``skill_to_kind``、PRD/API ``Task.kind`` 一致；``LONG_TOOLS`` 为长工具
名集（带动作后缀），供 M4 ``gates.py``/M6 ``rules.py`` 做门禁（M5-D6）。
"""

from __future__ import annotations

from uuid import uuid4

from app.errors import AppError, ErrorCode
from app.models import AuditLog, Task

# Task.kind 短名（与 M10 skill_to_kind、PRD/API Task.kind 一致）
TASK_KINDS: frozenset[str] = frozenset({"benchmark", "testcase", "rag", "stress"})

# 长工具名集（带动作后缀，供 M4 gates.py / M6 rules.py 识别长工具做门禁；
# 与 Task.kind 短名分离：benchmark↔benchmark.run 等由路由层对照表维护）
LONG_TOOLS: frozenset[str] = frozenset(
    {"benchmark.run", "testcase.generate", "rag.evaluate", "stress.run"}
)

# 活动任务状态（与 M3 episodic.get_active_tasks 同源）
_ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running", "awaiting_case_confirm")


def count_active_tasks(
    db,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> int:
    """统计活动任务数（P4-2 资源配额）；按用户或会话过滤。"""
    from app.models import Task

    query = db.query(Task).filter(Task.status.in_(_ACTIVE_STATUSES))
    if user_id:
        query = query.filter(Task.created_by == user_id)
    if session_id:
        query = query.filter(Task.session_id == session_id)
    return query.count()


def enqueue_long_task(
    db,
    session_id: str,
    user_id: str,
    kind: str,
    spec: dict,
    *,
    parent_task_id: str | None = None,
    commit: bool = True,
) -> str:
    """创建 queued Task + AuditLog，交 Worker 消费；返回 task_id。

    不阻塞对话回合。kind 取 Task.kind 短名 ∈ TASK_KINDS，否则抛
    AppError(VALIDATION)。``rag`` 未接入时禁止 mock succeeded（MEM-5，
    由 Worker 侧保证失败）。spec 写入 ``config``，``user_id`` 写入
    ``created_by``（对齐 REST create_task 语义）。

    ``commit=False`` 时只 flush，由调用方在同一事务内继续写（例如确认卡
    清卡）后再一次 commit，避免入队成功、卡标未清的半提交。
    """
    if kind not in TASK_KINDS:
        raise AppError(ErrorCode.VALIDATION, f"未知任务类型：{kind}")
    task = Task(
        id=uuid4().hex,
        session_id=session_id,
        created_by=user_id,
        kind=kind,
        status="queued",
        config=spec,
        parent_task_id=parent_task_id,
    )
    db.add(task)
    db.flush()
    db.add(
        AuditLog(
            user_id=user_id,
            action="task.create",
            target_type="task",
            target_id=task.id,
            detail={"kind": kind},
        )
    )
    if commit:
        db.commit()
    return task.id
