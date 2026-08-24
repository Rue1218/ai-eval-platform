"""Harness 编排层：会话级长工具门禁（M4 阶段 2，OR-6/OR-7）。

``LONG_TOOLS`` 为长工具名集（同一份在 M5 worker_bridge 与 M6 rules）；本层
提供会话级门禁查询（占槽检查）。规则门禁（M6 rules.py）只消费 GateContext
不查 DB（M6-D2）；本层负责把 DB 事实填入 GateContext（M6-D3 节点侧）。
"""

from __future__ import annotations

from app.harness.execution.worker_bridge import LONG_TOOLS


def is_long_tool(name: str) -> bool:
    """长工具判定（对话回合内禁止同步执行，OR-6）。"""
    return name in LONG_TOOLS


def check_session_active_task(db, session_id: str) -> bool:
    """会话是否存在非终态任务（OR-7 占槽门禁）。

    非终态集合与 M3 episodic.get_active_tasks 同源（queued/running/
    awaiting_case_confirm），避免双副本漂移。
    """
    from app.harness.memory.episodic import get_active_tasks

    return bool(get_active_tasks(db, session_id))
