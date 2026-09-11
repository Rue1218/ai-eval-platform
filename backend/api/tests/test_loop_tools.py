"""新工具调度的真实文件回填、滚动并发、审批、失败与取消验证。"""

import asyncio
import threading
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolResult
from app.harness.execution.approval import ApprovalBroker
from app.harness.execution.context import ToolExecutionContext
from app.harness.execution.loop_bridge import PlatformToolBridge
from app.harness.execution.loop_tools import ToolExecutionResult, normalize_tool_output
from app.harness.execution.registry import ToolRegistry, build_default_registry
from app.harness.execution.scheduler import ToolScheduler
from app.harness.execution.task_contract import (
    TASK_TOOL_MCP_NAMES,
    TASK_TOOL_NAMES,
    TASK_TOOL_WIRE_NAMES,
)


class MemoryLog:
    """只用于调度单测的记录端口，持久隔离另由真实 PG 用例验证。"""

    def __init__(self, session_id="test-session"):
        """每例独立事实列表。"""
        self.session_id, self.events = session_id, []

    def append(self, kind, data):
        """与正式 SessionLog 使用相同返回形状。"""
        event = {"seq": len(self.events), "ts": 0, "type": kind, "data": deepcopy(data)}
        self.events.append(event)
        return event


def settings(approval=False):
    """使用源 dsh 配置字段。"""
    return SimpleNamespace(dsh_require_approval=approval, dsh_max_parallel_tool_calls=2,
                           dsh_approval_timeout_seconds=0.1)


def call(name, id="c1", **args):
    """源 AssistantAttempt 已解析的调用形状。"""
    return {"id": id, "name": name, "args": args}


def results(log):
    """取持久顺序的工具终态。"""
    return [e["data"] for e in log.events if e["type"] == "tool/result"]


async def run(scheduler, calls, log=None, **extra):
    """直接调用源 execute 接口，不经过旧 toolnode。"""
    log = log or MemoryLog()
    messages = await scheduler.execute(session_id=log.session_id, log=log, turn=1, step=1,
                                       attempt_id="a1", calls=calls, emit=lambda e: None,
                                       allow_dispatch=True, **extra)
    return messages, log


class DuckTool:
    """不依赖 BaseTool 的最小可执行工具。"""

    schema = {"type": "object", "properties": {"i": {"type": "integer"}}}

    def __init__(self, name, body, mode="parallel", **metadata):
        """通过元数据声明并发和取消能力。"""
        self.name, self.ainvoke = name, body
        self.metadata = {"dsh_execution_mode": mode, "dsh_access": "read", **metadata}


def bridge_for(tmp_path, *, registry=None, names=("read", "write", "edit"), authorize=None, **kwargs):
    """可信临时工作区上下文；权限回调显式注入，不借生产配置开关。"""
    def context(identity):
        """身份来自 scheduler，工作区由服务端绑定。"""
        return ToolExecutionContext(session_id=identity["session_id"], user_id="test-user",
                                    sandbox_dir=str(tmp_path), sandbox_mode="workspace-write")

    return PlatformToolBridge(registry or build_default_registry(), allowed_tools=names,
                              context_factory=context, authorize=authorize or (lambda *args: None), **kwargs)


def test_task_tools_share_registry_schema_and_publish_safe_wire_names(tmp_path):
    """任务工具只从注册表投影 Schema，模型侧继续使用无点号的安全 wire 名。"""
    from jsonschema import Draft202012Validator

    async def business(*_args):
        """创建任务的确认桥替身，仅用于验证工具可见性。"""
        return ToolExecutionResult("{}", "succeeded")

    async def mcp(*_args):
        """查询/取消 MCP 桥替身，仅用于验证工具可见性。"""
        return ToolExecutionResult("{}", "succeeded")

    registry = build_default_registry()
    bridge = bridge_for(tmp_path, registry=registry, names=TASK_TOOL_NAMES,
                        business=business, mcp=mcp)
    specs = {spec.name: spec for spec in bridge.specs()}

    assert set(specs) == set(TASK_TOOL_WIRE_NAMES.values())
    for registry_name in TASK_TOOL_NAMES:
        wire_name = TASK_TOOL_WIRE_NAMES[registry_name]
        definition = registry.get(registry_name)
        assert specs[wire_name].parameters == dict(definition.parameters_schema)
        assert specs[wire_name].parameters["additionalProperties"] is False
        Draft202012Validator.check_schema(specs[wire_name].parameters)
        assert bridge.wire_to_name[wire_name] == registry_name
        assert bridge.wire_to_name[registry_name] == registry_name
        assert bridge.wire_to_name[TASK_TOOL_MCP_NAMES[registry_name]] == registry_name


@pytest.mark.asyncio
async def test_task_status_accepts_registered_wire_short_and_mcp_names(tmp_path):
    """同一任务状态工具可兼容三种既有名称，仍只路由到同一个 MCP tool_id。"""
    invoked = []

    async def mcp(definition, arguments, _context, identity):
        """记录实际 MCP 路由与保留的回传 wire 名。"""
        invoked.append((definition.name, definition.tool_id, dict(arguments), identity["wire_name"]))
        return ToolExecutionResult("{}", "succeeded")

    bridge = bridge_for(tmp_path, names=("task.status",), mcp=mcp)
    aliases = (
        TASK_TOOL_WIRE_NAMES["task.status"],
        "task.status",
        TASK_TOOL_MCP_NAMES["task.status"],
    )
    _, log = await run(
        ToolScheduler(settings(), bridge.available_tools()),
        [call(name, f"call-{index}", task_id=f"task-{index}") for index, name in enumerate(aliases)],
    )

    assert [item[0] for item in invoked] == ["task.status"] * len(aliases)
    assert [item[1] for item in invoked] == [TASK_TOOL_MCP_NAMES["task.status"]] * len(aliases)
    assert [item[3] for item in invoked] == list(aliases)
    dispatches = [event["data"] for event in log.events if event["type"] == "tool/dispatch"]
    assert [item["name"] for item in dispatches] == list(aliases)
    assert all(item["registry_name"] == "task.status" for item in dispatches)
    assert [item["wire_name"] for item in dispatches] == list(aliases)


@pytest.mark.asyncio
async def test_rolling_parallel_barrier_and_order():
    """较快调用完成即补位，较早调用未完成时结果仍不能越序提交。"""
    first_release, third_started = asyncio.Event(), asyncio.Event()
    started, finished = [], []

    async def read(args):
        """第一项挂起，第二项结束后第三项必须立即获得槽位。"""
        i = args["i"]
        started.append(i)
        if i == 1:
            await first_release.wait()
        if i == 3:
            third_started.set()
        finished.append(i)
        return str(i)

    async def write(args):
        """独占项启动时，前一组已全部结束。"""
        assert set(finished) == {1, 2, 3}
        started.append(4)
        return "write"

    log = MemoryLog()
    scheduler = ToolScheduler(settings(), [DuckTool("r", read), DuckTool("w", write, "exclusive")])
    task = asyncio.create_task(run(scheduler, [call("r", str(i), i=i) for i in (1, 2, 3)] + [call("w", "4")], log))
    await asyncio.wait_for(third_started.wait(), 1)
    assert started == [1, 2, 3]
    assert results(log) == []
    first_release.set()
    messages, _ = await task
    assert [m["tool_call_id"] for m in messages] == ["1", "2", "3", "4"]
    assert [r["call_id"] for r in results(log)] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_failure_bad_args_unknown_and_denial_do_not_failfast():
    """四类普通单项失败后，后续独占项仍真实执行。"""
    executed = []

    async def body(args):
        """返回明确失败或成功，记录实际执行次数。"""
        executed.append(args["i"])
        return "error: failed" if args["i"] == 1 else "ok"

    scheduler = ToolScheduler(settings(), [DuckTool("t", body, "exclusive")])
    messages, log = await run(scheduler, [call("t", "1", i=1),
        {"id": "2", "name": "t", "arguments_raw": "{", "parse_error": "bad json"},
        call("missing", "3"), call("t", "4", extra=True), call("t", "5", i=5)])
    assert executed == [1, 5]
    assert [r["status"] for r in results(log)] == ["failed"] * 4 + ["succeeded"]
    assert len(messages) == 5


@pytest.mark.asyncio
async def test_cancel_drains_preserves_known_and_marks_remainder():
    """保留已知完成、取消已确认项，尚未派发项全部记 not_started。"""
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def body(args):
        """模拟工具取消后清理，清理完才能返回取消终态。"""
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            return ToolExecutionResult("cancelled", "cancelled")

    log = MemoryLog()
    scheduler = ToolScheduler(settings(), [DuckTool("t", body, "exclusive")])
    task = asyncio.create_task(run(scheduler, [call("t", "1"), call("t", "2")], log))
    await entered.wait()
    task.cancel()
    await cleaning.wait()
    task.cancel()
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [r["status"] for r in results(log)] == ["cancelled", "not_started"]


@pytest.mark.asyncio
async def test_self_cancel_is_unknown_and_sibling_continues():
    """没有明确终止契约的自取消必须记未知，兄弟结果仍保留。"""
    async def body(args):
        """同组一个自取消，一个成功。"""
        if args["i"] == 1:
            raise asyncio.CancelledError
        return "ok"

    _, log = await run(ToolScheduler(settings(), [DuckTool("t", body)]), [call("t", "1", i=1), call("t", "2", i=2)])
    assert [r["status"] for r in results(log)] == ["outcome_unknown", "succeeded"]


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["deny", "timeout", "unavailable"])
async def test_approval_denial_then_continue(decision):
    """拒绝、超时与无通道都生成 denied，后续只读调用仍运行。"""
    broker = ApprovalBroker()
    executed = []

    async def gate(payload):
        """模拟经身份校验的控制回执。"""
        if decision == "timeout":
            await asyncio.Event().wait()
        return decision

    async def body(args):
        """记录获准执行的只读调用。"""
        executed.append(True)
        return "ok"

    if decision != "unavailable":
        broker.register("test-session", gate)
    tool = DuckTool("w", body, "exclusive", dsh_access="write")
    scheduler = ToolScheduler(settings(True), [tool, DuckTool("r", body)], approval_broker=broker)
    _, log = await run(scheduler, [call("w", "1"), call("r", "2")])
    assert executed == [True]
    assert [r["status"] for r in results(log)] == ["denied", "succeeded"]


@pytest.mark.asyncio
async def test_cancel_while_waiting_approval_never_dispatches():
    """取消 Future 留下审批取消事实，并为所有未派发工具补结果。"""
    entered = asyncio.Event()
    broker, log = ApprovalBroker(), MemoryLog()

    async def gate(payload):
        """模拟可取消的 pending_confirm 等待。"""
        entered.set()
        await asyncio.Event().wait()

    async def body(args):
        """取消审批的工具不应进入此处。"""
        pytest.fail("未经允许执行")

    broker.register(log.session_id, gate)
    scheduler = ToolScheduler(settings(True), [DuckTool("w", body, "exclusive", dsh_access="write")], approval_broker=broker)
    task = asyncio.create_task(run(scheduler, [call("w", "1"), call("w", "2")], log))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [r["status"] for r in results(log)] == ["not_started", "not_started"]
    assert next(e for e in log.events if e["type"] == "approval/decided")["data"]["outcome"] == "cancelled"
    assert not any(e["type"] == "tool/dispatch" for e in log.events)


@pytest.mark.asyncio
async def test_real_workspace_write_edit_read_and_failure(tmp_path):
    """真实平台 handler 修改临时文件，失败后继续 read，回填包含完整正文。"""
    bridge = bridge_for(tmp_path)
    calls = [call("write", "1", path="note.txt", content="alpha\nbeta\n"),
             call("write", "2", file_path="note.txt", content="should not overwrite"),
             call("edit", "3", path="note.txt", old="alpha", new=""),
             call("read", "4", file_path="note.txt")]
    messages, log = await run(ToolScheduler(settings(), bridge.available_tools()), calls)
    assert (tmp_path / "note.txt").read_text() == "\nbeta\n"
    assert "beta" in messages[-1]["content"]
    assert [r["status"] for r in results(log)] == ["succeeded", "failed", "succeeded", "succeeded"]
    dispatch = next(e["data"] for e in log.events if e["type"] == "tool/dispatch")
    assert dispatch["scope_path"].casefold() == str(tmp_path).casefold()
    assert dispatch["access"] == "write" and dispatch["execution_id"]
    assert dispatch["normalized_args"]["file_path"] == "note.txt"
    assert calls[0]["args"]["path"] == "note.txt"


@pytest.mark.asyncio
async def test_workspace_image_and_search_tools_are_parallel_and_keep_image_bytes_out_of_log(tmp_path):
    """图片只回填当前模型回合，glob/grep 只枚举受控工作区的普通文本文件。"""
    import struct

    (tmp_path / "images").mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 2, 3)
    (tmp_path / "images" / "chart.png").write_bytes(png)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("needle = 1\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("needle = 2\n", encoding="utf-8")

    bridge = bridge_for(tmp_path, names=("read_image", "glob", "grep"))
    messages, log = await run(
        ToolScheduler(settings(), bridge.available_tools()),
        [
            call("read_image", "image", file_path="images/chart.png"),
            call("glob", "glob", pattern="*.py"),
            call("grep", "grep", pattern="needle", include="*.py"),
        ],
    )

    image_content = messages[0]["content"]
    assert isinstance(image_content, list)
    assert image_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "src/main.py" in messages[1]["content"]
    assert "hidden.py" not in messages[1]["content"]
    assert "src/main.py:1:needle = 1" in messages[2]["content"]
    image_event = next(item for item in results(log) if item["name"] == "read_image")
    assert "data:image" not in image_event["content"]
    assert "2×3" in image_event["content"]


@pytest.mark.asyncio
async def test_workspace_search_tools_reject_traversal_and_bad_image_format(tmp_path):
    """搜索与图片读取都复用工作区实路径边界，不能通过绝对路径或伪图片绕过。"""
    (tmp_path / "fake.bin").write_bytes(b"not an image")
    bridge = bridge_for(tmp_path, names=("read_image", "glob", "grep"))
    _, log = await run(
        ToolScheduler(settings(), bridge.available_tools()),
        [
            call("glob", "glob", pattern="*", path="../outside"),
            call("grep", "grep", pattern="[", path="."),
            call("read_image", "image", file_path="fake.bin"),
        ],
    )
    assert [item["status"] for item in results(log)] == ["failed", "failed", "failed"]


@pytest.mark.asyncio
async def test_alias_conflict_traversal_and_source_offsets(tmp_path):
    """拒绝歧义和越界；源 1-based 显式转换，平台 offset 保持 0-based。"""
    (tmp_path / "x").write_text("zero\none\ntwo\n")
    bridge = bridge_for(tmp_path, names=("read",))
    _, log = await run(ToolScheduler(settings(), bridge.tools), [call("read", "1", path="x", file_path="other"), call("read", "2", file_path="../outside"), call("read", "3", file_path="x", offset=1, limit=1)])
    assert [r["status"] for r in results(log)] == ["failed", "failed", "succeeded"]
    assert "one" in results(log)[2]["content"]
    bridge = bridge_for(tmp_path, names=("read",), source_contract="deepseek-harness.v1")
    messages, _ = await run(ToolScheduler(settings(), bridge.tools), [call("read", file_path="x", offset=1, limit=1)])
    assert "zero" in messages[0]["content"]


@pytest.mark.asyncio
async def test_permissions_rechecked_after_approval(tmp_path):
    """等待审批期间撤权，allow 也不能派发。"""
    allowed = True
    broker = ApprovalBroker()

    def authorize(*args):
        """主服务动态 ACL 检查。"""
        if not allowed:
            raise AppError(ErrorCode.UNAUTHORIZED, "成员已撤权")

    async def gate(payload):
        """审批与平台权限是独立维度。"""
        nonlocal allowed
        allowed = False
        return "allow"

    broker.register("test-session", gate)
    bridge = bridge_for(tmp_path, authorize=authorize)
    _, log = await run(ToolScheduler(settings(True), bridge.tools, approval_broker=broker), [call("write", path="x", content="blocked")])
    assert results(log)[0]["status"] == "denied"
    assert not (tmp_path / "x").exists()
    assert not any(e["type"] == "tool/dispatch" for e in log.events)


@pytest.mark.asyncio
async def test_cancel_real_thread_waits_for_actual_write(tmp_path):
    """取消不能把仍会写入的线程当作已停止；join 后保留实际成功。"""
    entered, release = threading.Event(), threading.Event()
    registry = ToolRegistry()
    definition = build_default_registry().get("write")

    def delayed(args, root, context):
        """等待测试释放后调用真实平台文件 handler。"""
        entered.set()
        assert release.wait(5)
        return definition.handler(args, root, context)

    registry.register(replace(definition, handler=delayed))
    bridge, log = bridge_for(tmp_path, registry=registry, names=("write",)), MemoryLog()
    task = asyncio.create_task(run(ToolScheduler(settings(), bridge.tools), [call("write", "1", path="x", content="real"), call("write", "2", path="y", content="never")], log))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and results(log) == []
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (tmp_path / "x").read_text() == "real"
    assert not (tmp_path / "y").exists()
    assert [r["status"] for r in results(log)] == ["succeeded", "not_started"]


@pytest.mark.asyncio
async def test_runner_connection_unknown_and_no_raw_fallback(tmp_path):
    """Runner 连接不可证实不能记普通失败，更不能降级到原 bash handler。"""
    observed = []

    async def runner(definition, args, context, identity):
        """验证受控身份与墙钟时间已传到 Runner 接缝。"""
        observed.append(identity)
        raise ConnectionError("network unavailable")

    bridge = bridge_for(tmp_path, names=("bash",), runner=runner, runner_instance_id="runner-1")
    _, log = await run(ToolScheduler(settings(), bridge.tools), [call("bash", command="echo controlled", timeout=60000)])
    assert results(log)[0]["status"] == "outcome_unknown"
    assert observed[0]["effective_timeout_s"] == 15
    assert observed[0]["scope_path"].casefold() == str(tmp_path).casefold()
    assert bridge_for(tmp_path, names=("bash",)).available_tools() == []


def test_result_contract_retains_six_statuses_and_model_body():
    """结果状态显式，read 模型正文优先于浏览器摘要。"""
    for status in ("succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown"):
        result = ToolExecutionResult("body", status)
        assert normalize_tool_output(result) == result
        assert result.ok == (status == "succeeded")
    result = normalize_tool_output(ToolResult("read", True, {"summary": "preview", "model_text": "full body"}))
    assert result.content == "full body"
    assert normalize_tool_output({"status": "queued"}).status == "failed"


def test_always_grant_is_scoped_and_controller_cleanup():
    """跨工作区/控制器不继承 always，旧连接清理不能移除新 gate。"""
    broker = ApprovalBroker()
    first, second = object(), object()
    broker.register("s", first)
    broker.allow_always("s", "write", "owner/workspace1")
    assert broker.is_always_allowed("s", "write", "owner/workspace1")
    assert not broker.is_always_allowed("s", "write", "owner/workspace2")
    broker.register("s", second)
    broker.unregister("s", first)
    assert broker.gate_for("s") is second
    assert not broker.is_always_allowed("s", "write", "owner/workspace1")


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", ["success", "unknown", "missing_evidence", "wrong_fingerprint", "tombstone"])
async def test_runner_receipt_evidence_controls_result(tmp_path, receipt):
    """停止证据、代次、指纹全部对齐才允许给 Store 可释放终态。"""
    from app.harness.execution.loop_runner import RunnerResult

    async def runner(definition, args, context, identity):
        """直接返回 Runner 客户端的正式收据。"""
        assert identity["runner_request"].fingerprint == identity["request_fingerprint"]
        values = dict(execution_id=identity["execution_id"], runner_instance_id=identity["runner_instance_id"],
                      status="succeeded", process_tree_terminated=True, termination_evidence="process_exited",
                      execution_started=True, request_fingerprint=identity["request_fingerprint"], output="done")
        if receipt == "unknown":
            values.update(status="outcome_unknown", process_tree_terminated=False)
        elif receipt == "missing_evidence":
            values.update(termination_evidence=None)
        elif receipt == "wrong_fingerprint":
            values.update(request_fingerprint="wrong")
        elif receipt == "tombstone":
            values.update(status="not_started", execution_started=False, termination_evidence="not_started", request_fingerprint=None)
        return RunnerResult(**values)

    bridge = bridge_for(tmp_path, names=("bash",), runner=runner, runner_instance_id="instance-1")
    _, log = await run(ToolScheduler(settings(), bridge.tools), [call("bash", command="echo controlled")])
    expected = {"success": "succeeded", "tombstone": "not_started"}.get(receipt, "outcome_unknown")
    assert results(log)[0]["status"] == expected


@pytest.mark.asyncio
async def test_approval_stable_short_identity_and_projection_fields():
    """超长供应商 call ID 也只产生固定长度 UUID，WS 可取得完整调用身份。"""
    from app.harness.execution.approval import request_approval

    log, broker = MemoryLog(), ApprovalBroker()
    log.actor_id = "actor"

    async def gate(payload):
        """已验证的允许回执。"""
        return "allow"

    broker.register(log.session_id, gate)
    kwargs = dict(session_id=log.session_id, log=log, turn=1, step=1, attempt_id="a" * 200,
                  call=call("write", "c" * 200), emit=lambda e: None, approval_broker=broker)
    await request_approval(**kwargs)
    await request_approval(**kwargs)
    asked = [e["data"] for e in log.events if e["type"] == "approval/asked"]
    assert asked[0]["interaction_id"] == asked[1]["interaction_id"]
    assert len(asked[0]["interaction_id"]) == 36
    assert asked[0]["turn_id"] == "test-session:1"
    assert asked[0]["name"] == "write" and asked[0]["owner_user_id"] == "actor"
    assert log.events[-1]["data"]["source_outcome"] == "allowed"
