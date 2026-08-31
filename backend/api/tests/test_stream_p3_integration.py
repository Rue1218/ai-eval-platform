"""P3 集成测试：真实 bwrap 屏障、WS 重连、team 瞬态广播、ToolCard call_id 乱序。

规划稿 §8 要求的四类集成场景。bwrap 在 Windows / 无 bubblewrap 的环境自动跳过，
不假成功。不新增 WS 事件名。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from shared.sandbox_kernel import SandboxError, probe_sandbox, run_sandboxed

import app.harness.execution.dispatch as dispatch_mod
import app.harness.execution.toolnode as toolnode_mod
from app.errors import AppError, ErrorCode
from app.harness.execution import (
    NativeToolResultStore,
    ToolDef,
    ToolRegistry,
    build_default_registry,
    build_tool_node,
)
from app.harness.execution.batch import build_tool_batch
from app.harness.execution.stream_metrics import get_default_stream_metrics
from app.routers import ws
from app.session_connections import SessionConnectionHub


def _map_kernel_run(cmd: str, **kwargs):
    """把内核 SandboxError 映射为 api AppError，供 ToolNode 走真实 bwrap。"""
    try:
        return run_sandboxed(
            cmd,
            sandbox_dir=kwargs["sandbox_dir"],
            timeout_s=kwargs["timeout_s"],
            limits=kwargs.get("limits"),
            max_output_chars=kwargs.get("max_output_chars", 20000),
            on_output=kwargs.get("on_output"),
        )
    except SandboxError as exc:
        mapping = {
            "TIMEOUT": ErrorCode.TIMEOUT,
            "VALIDATION": ErrorCode.VALIDATION,
            "INTERNAL": ErrorCode.INTERNAL,
        }
        raise AppError(mapping.get(exc.code, ErrorCode.INTERNAL), exc.message) from exc


async def _drain_toolnode(node, state: dict) -> list[dict]:
    """按图语义循环访问 ToolNode，直到批次清空。"""
    visits: list[dict] = []
    current = dict(state)
    while current.get("pending_tool"):
        out = await node(current)
        visits.append(out)
        current = {**current, **out}
    return visits


def test_toolnode_bash_exclusive_wave_when_parallel_enabled(monkeypatch) -> None:
    """无 bwrap 时仍验证：并行开启后 bash 与独立 read 分两次访问，不进入同一 TaskGroup。"""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", True)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    get_default_stream_metrics().reset()
    order: list[str] = []

    def bash_handler(arguments, sandbox_dir, _context) -> str:
        order.append("bash")
        path = os.path.join(sandbox_dir or "", "created.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(arguments.get("command") or "ok"))
        return "wrote"

    def read_handler(arguments, sandbox_dir, _context) -> str:
        order.append("read")
        path = os.path.join(sandbox_dir or "", str(arguments.get("path") or ""))
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="bash",
            description="独占写",
            parameters_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
            permission="sandbox.bash",
            timeout_s=3.0,
            handler=bash_handler,
            transport="native",
            contextual=True,
            concurrency_class="exclusive",
        )
    )
    registry.register(
        ToolDef(
            name="read",
            description="读文件",
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            permission="sandbox.read",
            timeout_s=3.0,
            handler=read_handler,
            transport="native",
            contextual=True,
            concurrency_class="path_scoped",
        )
    )
    bash_call = {
        "call_id": "call_bash",
        "name": "bash",
        # 本用例仅验证 bash 的独占波次；使用白名单只读命令，避免把未经过
        # LangGraph HITL 确认的模拟写命令带入这里的直调 ToolNode。
        "arguments": {"command": "pwd"},
        "native": True,
    }
    read_call = {
        "call_id": "call_read",
        "name": "read",
        "arguments": {"path": "created.txt"},
        "native": True,
    }
    batch = build_tool_batch([bash_call, read_call], batch_id="batch_bash_fake")
    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {
        "configurable": {"thread_id": "p3-bash-fake", "profile": {"id": "p-test"}}
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            node = build_tool_node(
                registry, native_tool_results=NativeToolResultStore(), sandbox_dir=tmp
            )
            visits = asyncio.run(
                _drain_toolnode(
                    node,
                    {
                        "request": {"config": {}, "messages": ()},
                        "pending_tool": bash_call,
                        "pending_tools": [read_call],
                        "pending_tool_batch": batch,
                    },
                )
            )
    finally:
        toolnode_mod.get_config = original

    assert order == ["bash", "read"]
    assert len(visits) == 2
    assert [
        event["payload"]["call_id"]
        for event in visits[0]["pending_events"]
        if event["kind"] == "tool_result"
    ] == ["call_bash"]
    assert [
        event["payload"]["call_id"]
        for event in visits[1]["pending_events"]
        if event["kind"] == "tool_result"
    ] == ["call_read"]
    assert [message["tool_call_id"] for message in visits[1]["native_messages"]] == [
        "call_bash",
        "call_read",
    ]


@pytest.mark.skipif(
    not probe_sandbox(),
    reason="bwrap 不可用（缺失或 userns/seccomp 拦截），跳过真实沙箱屏障测试",
)
def test_bwrap_bash_serial_barrier_when_parallel_enabled(monkeypatch) -> None:
    """并行开关打开后，bash 仍独占波次；真实 bwrap 先写文件，随后 read 才能看见。"""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", True)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    monkeypatch.setattr(settings, "sandbox_engine", "bwrap")
    monkeypatch.setattr(dispatch_mod, "run_sandboxed", _map_kernel_run)
    get_default_stream_metrics().reset()

    bash_call = {
        "call_id": "call_bash",
        "name": "bash",
        "arguments": {"command": "echo hello > created.txt"},
        "native": True,
    }
    read_call = {
        "call_id": "call_read",
        "name": "read",
        "arguments": {"path": "created.txt"},
        "native": True,
    }
    batch = build_tool_batch([bash_call, read_call], batch_id="batch_bash_barrier")
    configurable = {
        "thread_id": "p3-bash-barrier",
        "profile": {"id": "p-test"},
    }
    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {"configurable": configurable}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            node = build_tool_node(
                build_default_registry(),
                native_tool_results=NativeToolResultStore(),
                sandbox_dir=tmp,
            )
            visits = asyncio.run(
                _drain_toolnode(
                    node,
                    {
                        "request": {"config": {}, "messages": ()},
                        "pending_tool": bash_call,
                        "pending_tools": [read_call],
                        "pending_tool_batch": batch,
                    },
                )
            )
            created = os.path.join(tmp, "created.txt")
            assert os.path.isfile(created)
            with open(created, encoding="utf-8") as handle:
                assert "hello" in handle.read()
    finally:
        toolnode_mod.get_config = original

    assert len(visits) == 2
    first_results = [
        event["payload"]["call_id"]
        for event in visits[0]["pending_events"]
        if event["kind"] == "tool_result"
    ]
    second_results = [
        event["payload"]["call_id"]
        for event in visits[1]["pending_events"]
        if event["kind"] == "tool_result"
    ]
    assert first_results == ["call_bash"]
    bash_payload = next(
        event["payload"]
        for event in visits[0]["pending_events"]
        if event["kind"] == "tool_result"
    )
    assert bash_payload["ok"] is True
    assert second_results == ["call_read"]
    read_payload = next(
        event["payload"]
        for event in visits[1]["pending_events"]
        if event["kind"] == "tool_result"
    )
    assert read_payload["ok"] is True
    assert visits[1]["pending_tool"] is None
    assert [message["tool_call_id"] for message in visits[1]["native_messages"]] == [
        "call_bash",
        "call_read",
    ]


class _FakeWS:
    """记录下发帧与关闭码的 WebSocket 桩。"""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.close_code: int | None = None

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


class _EventRow:
    """对齐 ws_events 行，供重连补发查询。"""

    def __init__(self, event_id: int, event: str, payload: dict, task_id: str | None = None):
        self.event_id = event_id
        self.event = event
        self.payload = payload
        self.task_id = task_id
        self.ts = datetime(2026, 8, 26, tzinfo=UTC)


@pytest.mark.asyncio
async def test_ws_reconnect_replays_persistent_not_transient() -> None:
    """last_event_id 只补发持久事件；瞬态 assistant_delta / tool_progress 不在库中。"""
    rows = [
        _EventRow(1, "user_message", {"text": "读两个文件"}),
        _EventRow(2, "tool_call", {"call_id": "call_a", "name": "read"}),
        _EventRow(3, "tool_call", {"call_id": "call_b", "name": "read"}),
        _EventRow(4, "tool_result", {"call_id": "call_b", "name": "read", "ok": True}),
        _EventRow(5, "tool_result", {"call_id": "call_a", "name": "read", "ok": True}),
        _EventRow(6, "assistant_message", {"text": "已汇总", "role": "assistant"}),
        _EventRow(7, "response.completed", {"finish_reason": "stop", "role": "assistant"}),
    ]

    class _Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return [row for row in rows if row.event_id > 2]

    class _Db:
        def query(self, *_args):
            return _Query()

    websocket = _FakeWS()
    state = ws._ConnectionState()
    await ws._replay_events(_Db(), websocket, state, "s-team", 2)

    kinds = [frame["event"] for frame in websocket.frames]
    assert kinds == [
        "tool_call",
        "tool_result",
        "tool_result",
        "assistant_message",
        "response.completed",
    ]
    assert [frame["event_id"] for frame in websocket.frames] == [3, 4, 5, 6, 7]
    assert "assistant_delta" not in kinds
    assert "tool_progress" not in kinds
    assert "tool_output_delta" not in kinds
    assert state.cursor == 7
    # 乱序完成的 tool_result 仍按落库 event_id 补发，call_id 保持原调用身份。
    results = [frame for frame in websocket.frames if frame["event"] == "tool_result"]
    assert [frame["payload"]["call_id"] for frame in results] == ["call_b", "call_a"]


@pytest.mark.asyncio
async def test_team_transient_broadcast_stays_in_session() -> None:
    """瞬态 chunk 只发给本会话在线成员；收回分享后协作者立刻 4404。"""
    hub = SessionConnectionHub()
    owner_ws, mate_ws, other_ws = _FakeWS(), _FakeWS(), _FakeWS()
    owner_state = SimpleNamespace(lock=asyncio.Lock(), cursor=4)
    mate_state = SimpleNamespace(lock=asyncio.Lock(), cursor=4)
    other_state = SimpleNamespace(lock=asyncio.Lock(), cursor=9)

    hub.register("c-owner", "s-team", "u-owner", owner_ws, owner_state)
    hub.register("c-mate", "s-team", "u-mate", mate_ws, mate_state)
    hub.register("c-other", "s-private", "u-other", other_ws, other_state)

    await hub.broadcast_chunk(
        "s-team",
        lambda cursor: ws._frame(
            "s-team",
            "tool_progress",
            cursor,
            {"call_id": "call_a", "name": "read", "stage": "executing", "message": "读取中"},
        ),
    )
    assert owner_ws.frames and mate_ws.frames
    assert owner_ws.frames[0]["event"] == "tool_progress"
    assert owner_ws.frames[0]["event_id"] == 4
    assert mate_ws.frames[0]["payload"]["call_id"] == "call_a"
    assert other_ws.frames == []

    await hub.close_non_owner("s-team", "u-owner")
    assert mate_ws.close_code == 4404
    owner_ws.frames.clear()
    mate_ws.frames.clear()

    await hub.broadcast_chunk(
        "s-team",
        lambda cursor: ws._frame(
            "s-team",
            "assistant_delta",
            cursor,
            {"role": "assistant", "text": "后续正文"},
        ),
    )
    assert owner_ws.frames and owner_ws.frames[0]["event"] == "assistant_delta"
    assert mate_ws.frames == []
    assert other_ws.frames == []


def _find_pending_tool(blocks: list[dict], name: object, call_id: object) -> dict | None:
    """与 frontend/src/utils/toolCard.ts findPendingToolItem 同一套关联规则。"""
    reversed_blocks = list(reversed(blocks))
    if isinstance(call_id, str) and call_id:
        return next(
            (
                block
                for block in reversed_blocks
                if block.get("type") == "tool"
                and block.get("callId") == call_id
                and block.get("status") == "pending"
            ),
            None,
        )
    return next(
        (
            block
            for block in reversed_blocks
            if block.get("type") == "tool"
            and block.get("tool") == name
            and block.get("status") == "pending"
        ),
        None,
    )


def test_toolcard_out_of_order_results_keep_call_id() -> None:
    """同名 read 乱序完成时按 call_id 回填，禁止串到另一张卡。"""
    blocks = [
        {"type": "tool", "callId": "call_a", "tool": "read", "status": "pending", "result": None},
        {"type": "tool", "callId": "call_b", "tool": "read", "status": "pending", "result": None},
    ]
    first_done = _find_pending_tool(blocks, "read", "call_b")
    assert first_done is blocks[1]
    first_done["status"] = "ok"
    first_done["result"] = "B"
    assert blocks[0]["status"] == "pending"
    assert blocks[0]["result"] is None

    second_done = _find_pending_tool(blocks, "read", "call_a")
    assert second_done is blocks[0]
    second_done["status"] = "ok"
    second_done["result"] = "A"
    assert [block["result"] for block in blocks] == ["A", "B"]

    # 无 call_id 的历史事件才退回同名最近 pending，不得改写已完成卡。
    blocks.append(
        {"type": "tool", "callId": "call_c", "tool": "read", "status": "pending", "result": None}
    )
    legacy = _find_pending_tool(blocks, "read", "")
    assert legacy is blocks[2]
    assert _find_pending_tool(blocks, "read", "call_b") is None
