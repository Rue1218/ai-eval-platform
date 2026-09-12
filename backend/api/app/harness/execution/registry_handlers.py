"""Harness 执行层：工具 handler 实现（M5，EX-1/EX-5）。

从 registry.py 拆出（2026-09-11 巨型文件治理）：19 个原生工具 handler；
重依赖经函数内导入（``from .dispatch import ...``）保持低耦合，
``build_default_registry`` 负责装配与注册。
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from app.errors import AppError, ErrorCode


def _media_mcp_unavailable_handler(
    _arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """媒体工具的防御性占位 handler；正常调用只能经远程 MCP provider。"""
    raise AppError(ErrorCode.VALIDATION, "媒体 MCP 未启用")


def _read_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """read 工具 handler：受控目录内读取相对路径（防目录穿越）。

    ``sandbox_dir`` 由平台经 dispatch 注入，**禁止模型传参**（M5-D7 红线）；
    ``offset``/``limit`` 支持长文本分段读取。
    """
    from .dispatch import read_file_safe, resolve_read_offset

    return read_file_safe(
        str(arguments.get("file_path") or arguments.get("path") or ""),
        sandbox_dir or "",
        offset=resolve_read_offset(arguments),
        limit=arguments.get("limit"),
        on_output=getattr(context, "report_output", None),
    )


def _read_image_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """read_image 工具 handler：只从受控工作区读取小型常见图片。"""
    from .dispatch import read_image_safe

    return read_image_safe(str(arguments.get("file_path") or ""), sandbox_dir or "")


def _glob_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """glob 工具 handler：在受控工作区枚举匹配文件。"""
    from .dispatch import glob_files_safe

    path = arguments.get("path")
    return glob_files_safe(
        str(arguments.get("pattern") or ""), sandbox_dir or "",
        str(path) if isinstance(path, str) else None,
    )


def _grep_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """grep 工具 handler：在受控工作区文本文件中执行受限正则搜索。"""
    from .dispatch import grep_files_safe

    path, include = arguments.get("path"), arguments.get("include")
    return grep_files_safe(
        str(arguments.get("pattern") or ""), sandbox_dir or "",
        path=str(path) if isinstance(path, str) else None,
        include=str(include) if isinstance(include, str) else None,
    )


def _write_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """write 工具 handler：受控目录内写入相对路径（防目录穿越）。"""
    from .dispatch import write_file_safe

    progress = getattr(context, "report_progress", None)
    if callable(progress):
        progress("writing", "正在以原子方式写入文件")
    result = write_file_safe(
        str(arguments.get("file_path") or arguments.get("path") or ""),
        str(arguments.get("content", "")),
        sandbox_dir or "",
    )
    reporter = getattr(context, "report_output", None)
    if callable(reporter) and result.preview:
        reporter("document", result.preview, 1)
    return result


def _edit_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """edit 工具 handler：受控目录内原子替换（防目录穿越）。"""
    from .dispatch import edit_file_safe

    return edit_file_safe(
        str(arguments.get("file_path") or arguments.get("path") or ""),
        str(arguments.get("old_string") or arguments.get("old") or ""),
        str(arguments.get("new_string") if arguments.get("new_string") is not None else arguments.get("new") or ""),
        sandbox_dir or "",
        replace_all=arguments.get("replace_all") is True,
    )


def _web_search_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """web_search 原生 handler：服务端 Firecrawl REST 适配器。"""
    from .dispatch import web_search

    progress = getattr(_context, "report_progress", None)
    if callable(progress):
        progress("searching", "正在请求受控网络检索服务")
    result = web_search(
        str(arguments.get("query", "")),
        limit=arguments.get("max_results", arguments.get("limit")),
        timeout_s=20.0,
    )
    if callable(progress):
        progress("formatting", "正在整理安全检索结果")
    return result


def _web_fetch_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """web_fetch 原生 handler：带 SSRF 防护的服务端抓取器。"""
    from .dispatch import apply_fetch_content_budget, assert_fetch_domains, web_fetch

    url = str(arguments.get("url", ""))
    assert_fetch_domains(
        url,
        allowed=arguments.get("allowed_domains"),
        blocked=arguments.get("blocked_domains"),
    )
    result = web_fetch(
        url,
        format=str(arguments.get("format") or "markdown"),
        timeout_s=20.0,
        on_output=getattr(_context, "report_output", None),
        on_progress=getattr(_context, "report_progress", None),
    )
    return apply_fetch_content_budget(result, arguments.get("max_content_tokens"))


def _task_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task 原生 handler：整表替换会话规划，并回传前端抽屉所需的真实步骤。"""
    from .dispatch import build_task_plan
    from .session_board import replace_plan_steps

    plan = build_task_plan(arguments)
    board = getattr(context, "session_tasks", None)
    if isinstance(board, list):
        replace_plan_steps(
            board,
            subject=plan.description or plan.goal[:24],
            description=plan.goal,
            steps=list(plan.steps),
        )
    return plan


def _board_from_context(context: object | None) -> list:
    """取出当前波次共享的会话看板；缺失时用空列表（不写回图状态）。"""
    board = getattr(context, "session_tasks", None)
    return board if isinstance(board, list) else []


def _session_task_create_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """会话看板创建一项，返回 task.id。"""
    from .session_board import BoardToolResult, create_task

    item = create_task(_board_from_context(context), arguments)
    return BoardToolResult("已创建会话任务", item)


def _session_task_get_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """按 taskId 读取看板项。"""
    from .session_board import BoardToolResult, get_task

    item = get_task(_board_from_context(context), str(arguments.get("taskId") or ""))
    if item is None:
        return BoardToolResult("任务不存在", {"task": None})
    return BoardToolResult("已读取会话任务", item)


def _session_task_update_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """更新看板项状态或字段。"""
    from .session_board import BoardToolResult, update_task

    item = update_task(
        _board_from_context(context),
        arguments,
        owner=str(getattr(context, "user_id", "") or ""),
    )
    return BoardToolResult("已更新会话任务", item)


def _session_task_list_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """列出未删除的会话任务。"""
    from .session_board import BoardToolResult, list_tasks

    items = list_tasks(_board_from_context(context))
    return BoardToolResult(
        f"当前清单 {len(items)} 项",
        {"tasks": items},
        model_text=f"会话任务 {len(items)} 项",
    )


def _ask_user_question_handler(
    arguments: Mapping[str, object],
    _sandbox_dir: str | None = None,
    _context: object | None = None,
) -> object:
    """提问在 ToolNode 内 interrupt；handler 不应被走到。"""
    raise AppError(ErrorCode.INTERNAL, "ask_user_question 必须由 ToolNode 挂起")


def _bash_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """bash 工具 handler：runner 容器内按网络模式执行（阶段 3 开放通用 bash）。

    资源限制读 Settings（内存/进程数/CPU），``sandbox_dir`` 由平台注入，
    禁止模型传参（M5-D7 红线）；无字符串词表/静态裁决——``mode`` 声明网络模式
    （isolated 断网 / network 保留网络），文件边界由容器挂载与权限档位审批承担；
    引擎为 "off" 或 runner 不可用时 fail-closed（VALIDATION），禁止降级为无隔离执行。
    """
    from app.config import settings
    from app.harness.execution.dispatch import BashResult, run_bash
    from app.harness.execution.sandbox import SandboxLimits
    from app.harness.security.exec_policy import resolve_bash_engine

    # #5：沙箱引擎决策收敛于 exec_policy.resolve_bash_engine（显式 Spec 决策，
    # 非 container 一律 fail-closed，禁止降级无隔离执行）
    verdict = resolve_bash_engine(settings.sandbox_engine)
    if not verdict.allow:
        raise AppError(ErrorCode.VALIDATION, verdict.reason)
    limits = SandboxLimits(
        memory_kb=settings.sandbox_memory_mb * 1024,
        nproc=settings.sandbox_nproc,
        cpu_s=settings.sandbox_cpu_s,
    )
    from .aliases import bash_timeout_seconds

    started = time.perf_counter()
    # 网络模式来源接缝——上下文（会话档位派生）优先，缺省回落全局 settings。
    mode = str(getattr(context, "sandbox_mode", "") or "") or settings.sandbox_bash_default_mode
    if sandbox_dir:
        # F5/G6（§6.6）：bash 工作区可写，写前容量检查（卷水位熔断优先）。
        from .quota import check_workspace_write_capacity

        check_workspace_write_capacity(sandbox_dir, extra_bytes=0)
    output = run_bash(
        str(arguments.get("command", "")),
        sandbox_dir=sandbox_dir or "",
        mode=mode,
        timeout_s=bash_timeout_seconds(arguments),
        limits=limits,
        on_output=getattr(context, "report_output", None),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return BashResult(output, duration_ms=duration_ms)


def _task_create_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task.create 工具 handler：长任务直接入队（platform.tasks MCP，P4-1）。

    会话/用户来自 ``ToolExecutionContext``（平台注入，模型不可传）；经
    ``task_tools.create_task_safe`` 校验并 ``enqueue_long_task``，返回
    ``{status: queued, task_id, kind}``，不等待 Worker 终态。
    """
    from .task_tools import create_task_safe

    return create_task_safe(arguments, context)


def _task_status_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task.status 工具 handler：只读查询任务状态（platform.tasks MCP，P4-1）。"""
    from .task_tools import status_task_safe

    return status_task_safe(arguments, context)


def _task_cancel_handler(
    arguments: Mapping[str, object],
    sandbox_dir: str | None = None,
    context: object | None = None,
) -> object:
    """task.cancel 工具 handler：行锁取消非终态任务（platform.tasks MCP，P4-1）。"""
    from .task_tools import cancel_task_safe

    return cancel_task_safe(arguments, context)
