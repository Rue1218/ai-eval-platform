"""Harness 反馈层：规则门禁先行（M6 阶段 2，FB-2）。

按八类门禁顺序做确定性检查（不调模型）：长工具/白名单/任意代码/一单一
kind/必填槽位/资产溯源/占槽/先评后压。门禁失败返回 ``GateResult``；
``assert_gates`` 抛 ``AppError``（VALIDATION/CONCURRENCY），由 M4 节点捕获
转 ``NodeEvent(error)``。会话级门禁（OR-6/7）由 M4 ``gates.py`` 承担，
本层只消费 ``GateContext`` 不查 DB（M6-D2）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall

# 确认卡 kind 白名单（一单一 kind 门禁）
CONFIRM_KINDS: frozenset[str] = frozenset({"benchmark", "testcase", "rag", "stress"})

# 任意代码黑名单前缀（bash 门禁；bwrap 沙箱之外的第二道防线，禁止命令开头命中）
BASH_BLOCK_PREFIXES: tuple[str, ...] = (
    "rm ",
    "sudo ",
    "curl ",
    "wget ",
    "nc ",
    "ssh ",
    "scp ",
    "chmod ",
    "chown ",
)


@dataclass(frozen=True, slots=True)
class GateContext:
    """门禁上下文（确定性，不含回调/连接）。

    ``has_active_task`` 由 M4 节点在调用前查 DB 填入（OR-7 会话级门禁同源）；
    ``registered_names``/``required_slots`` 由注册表提供（白名单/必填槽位）；
    ``owned_file_ids`` 为当前用户可用的附件 ID（资产溯源）。
    """

    session_id: str
    user_id: str
    has_active_task: bool = False
    owned_file_ids: frozenset[str] = frozenset()
    registered_names: frozenset[str] = frozenset()
    required_slots: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GateResult:
    """门禁结果：通过或失败（失败码为 ErrorCode.value）。"""

    passed: bool
    failed_code: str | None = None
    failed_message: str | None = None


def _is_long_tool(name: str) -> bool:
    """长工具判定（延迟导入避免与 execution 包循环依赖）。"""
    from app.harness.execution.worker_bridge import LONG_TOOLS

    return name in LONG_TOOLS


def check_gates(call: ToolCall, ctx: GateContext) -> GateResult:
    """8 类门禁顺序检查（FB-2）。失败返回 failed_code，不抛异常。"""
    name = call.name
    arguments = call.arguments or {}

    # 1. 长工具：对话回合内禁止同步执行（OR-6）
    if _is_long_tool(name):
        return GateResult(False, "VALIDATION", "长工具必须经任务队列由 Worker 执行")
    # 2. 白名单：未注册即拒绝（EX-5）
    if ctx.registered_names and name not in ctx.registered_names:
        return GateResult(False, "VALIDATION", f"工具未注册：{name}")
    # 3. 任意代码：bash 黑名单纵深防御（bwrap 沙箱之外的第二道防线）
    command = arguments.get("command")
    if name == "bash" and isinstance(command, str):
        stripped = command.lstrip()
        if any(stripped.startswith(prefix) for prefix in BASH_BLOCK_PREFIXES):
            return GateResult(False, "VALIDATION", "bash 命令命中黑名单")
    # 4. 一单一 kind：确认卡 kind 四选一，不混跑
    kind = arguments.get("kind")
    if kind is not None and kind not in CONFIRM_KINDS:
        return GateResult(False, "VALIDATION", f"未知任务类型：{kind}")
    # 5. 必填槽位：工具参数 schema required 缺失
    required = ctx.required_slots.get(name)
    if required:
        missing = [slot for slot in required if not arguments.get(slot)]
        if missing:
            return GateResult(False, "VALIDATION", f"缺少必填参数：{', '.join(missing)}")
    # 6. 资产溯源：file_id 非归属用户拒绝（EX-2）
    file_id = arguments.get("file_id")
    if file_id is not None and ctx.owned_file_ids and file_id not in ctx.owned_file_ids:
        return GateResult(False, "VALIDATION", "附件不属于当前用户")
    # 7. 占槽：会话存在活动任务时禁止再入队新任务（OR-7）。
    # task.cancel 不在此列：取消非终态任务正是其用途（API.md §3.6.1），
    # 须放行以释放占槽；task.status 只读同样不受限。
    if ctx.has_active_task and name == "task.create":
        return GateResult(False, "CONCURRENCY", "会话存在活动任务")
    # 8. 先评后压：stress 须由质量任务 succeeded 派生
    if name == "task.create" and kind == "stress":
        return GateResult(False, "VALIDATION", "压测任务须由质量评测成功派生")
    return GateResult(True)


def assert_gates(call: ToolCall, ctx: GateContext) -> None:
    """门禁失败抛 AppError（VALIDATION/CONCURRENCY）。"""
    result = check_gates(call, ctx)
    if result.passed:
        return
    code = ErrorCode.CONCURRENCY if result.failed_code == "CONCURRENCY" else ErrorCode.VALIDATION
    raise AppError(code, result.failed_message or "门禁未通过")
