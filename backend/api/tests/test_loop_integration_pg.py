"""真实 PG→Runtime→Attempt→ToolBridge→文件→历史回填→WS v2 集成。"""

from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.loop import TurnDependencies, build_agent
from app.agent.loop_service import LoopService
from app.agent.loop_settings import LoopSettings
from app.agent.runtime import AgentRuntime
from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.execution.context import ToolExecutionContext
from app.harness.execution.loop_bridge import PlatformToolBridge
from app.harness.execution.registry import ToolRegistry, build_default_registry
from app.harness.execution.scheduler import ToolScheduler
from app.harness.memory.agent_events import SessionLog
from app.harness.memory.agent_messages import derive_messages
from app.llm.loop_contracts import Done, LlmRequest, TextDelta, ToolCallDelta, ToolCallStart
from app.models import Message, Session, WorkspaceExecutionGuard
from app.routers.ws_v2 import WsV2Connection, parse_command
from app.session_access import require_visible_session
from tests import test_loop_store_pg as store_fixtures
from tests.test_loop_ws_handler import FakeSocket

# 显式复用 PG 夹具，避免重复建立/清理数据库测试身份。
pg_case = store_fixtures.pg_case


def make_command(sid, kind="turn.submit", data=None, request_id=None):
    """通过真实严格解析器生成规范命令及输入摘要。"""
    return parse_command(json.dumps({
        "protocol_version": 2, "type": kind, "request_id": request_id or str(uuid4()),
        "session_id": sid, "data": data or {},
    }))


def call_chunks(name, args, identity):
    """模型逐片提供原始参数，真实 Attempt 负责合并解析。"""
    raw = json.dumps(args, ensure_ascii=False)
    middle = len(raw) // 2
    return [
        ToolCallStart(0, identity, name), ToolCallDelta(0, raw[:middle]),
        ToolCallDelta(0, raw[middle:]), Done("tool_calls", {"completion_tokens": 2}),
    ]


class ScriptedAdapter:
    """只替换外部模型响应，记录收到的真实回填请求。"""

    def __init__(self, *scripts):
        """每个脚本对应一次真实模型 attempt。"""
        self.scripts = list(scripts)
        self.requests = []
        self.closed = False

    async def stream(self, request):
        """不伪造工具结果、事实或后续历史。"""
        self.requests.append(deepcopy(request))
        script = self.scripts.pop(0)
        for chunk in script:
            yield chunk

    async def aclose(self):
        """验证服务在回合收尾后释放模型资源。"""
        self.closed = True


class BlockingAdapter(ScriptedAdapter):
    """在真实模型流中阻塞，供取消/观察者断连用例控制。"""

    def __init__(self):
        """固定事件只用于测试同步，不模拟 Runtime 生命周期。"""
        super().__init__()
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def stream(self, request):
        """发送可保留正文前缀后等待取消。"""
        self.requests.append(deepcopy(request))
        try:
            yield TextDelta("已提交前缀")
            self.started.set()
            await asyncio.Event().wait()
        finally:
            self.stopped.set()


def builder_for(case, root, adapter, *, registry=None):
    """装配真实工具白名单/调度器，只注入受控测试模型和临时工作区。"""
    async def builder(service, entry, actor_id, data):
        """平台 ACL 与原生文件 handler 均保留，不 mock 关键回填。"""
        tool_registry = registry or build_default_registry()

        def context_factory(identity):
            """真实会话 ACL 配合 pytest 临时目录，不使用客户端 cwd。"""
            with case.factory() as db:
                require_visible_session(db, identity["session_id"], actor_id)
            return ToolExecutionContext(
                session_id=identity["session_id"], user_id=actor_id,
                sandbox_dir=str(root), sandbox_mode="workspace-write",
                call_id=identity["call_id"],
            )

        def authorize(definition, arguments, context):
            """再检查会话与已装配工具；路径边界由真实 handler 校验。"""
            with case.factory() as db:
                require_visible_session(db, context.session_id, actor_id)
            if definition.name not in {"read", "edit"}:
                raise AppError(ErrorCode.WHITELIST, "测试工具未授权")

        bridge = PlatformToolBridge(
            tool_registry, allowed_tools=("read", "edit"), context_factory=context_factory,
            authorize=authorize,
        )
        scheduler = ToolScheduler(service._settings(), bridge.available_tools(),
                                  approval_broker=service._broker)
        request = LlmRequest(
            model="isolated-fake", provider="openai", protocol="openai_chat",
            messages=[], system="隔离集成测试", tools=bridge.specs(), max_tokens=128,
            reasoning_effort="off",
        )
        return TurnDependencies(adapter, scheduler=scheduler, request=request), [adapter]
    return builder


async def wait_for(predicate, timeout=5):
    """限定等待时长，避免实现错误使测试永久挂住。"""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def current_card(case, sid):
    """从 PG 卡片事实读模型读取身份，不依赖 WS 内存对象。"""
    with case.factory() as db:
        return deepcopy(db.get(Session, sid).pending_confirm)


async def open_ws(service, actor, sid):
    """绕过票据签发，仅使用已认证 actor 驱动真实 WS/Service/PG。"""
    socket = FakeSocket(service)
    connection = WsV2Connection(socket, service, actor, poll_interval=0.005)
    task = asyncio.create_task(connection.run())
    await socket.push(session_id=sid)
    await wait_for(lambda: any(f["type"] == "replay.completed" for f in socket.sent))
    return socket, connection, task


async def close_ws(socket, task):
    """正常网络断开必须完成 owner 判定和注销。"""
    await socket.incoming.put(None)
    await asyncio.wait_for(task, 5)


def approval_command(sid, card, *, decision="allow", nonce=None, request_id=None):
    """只从已授权持久卡片复制完整交互身份。"""
    data = {key: card[key] for key in (
        "interaction_id", "turn_id", "turn", "attempt_id", "call_id", "nonce",
    )}
    if nonce is not None:
        data["nonce"] = nonce
    return make_command(sid, "approval.respond", {**data, "decision": decision},
                        request_id=request_id)


def test_pg_ws_read_edit_read_full_loop_card_acl_nonce_and_replay(pg_case, tmp_path, monkeypatch):
    """真实三工具循环、卡 ACL、错 nonce 拒绝、正确确认、模型正文回填与 WS 回放。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    file = tmp_path / "note.txt"
    file.write_text("old-title\nuntouched-sentinel\n", encoding="utf-8")
    sid = pg_case.session(team=True)
    adapter = ScriptedAdapter(
        call_chunks("read", {"file_path": "note.txt"}, "read-before"),
        call_chunks("edit", {"file_path": "note.txt", "old_string": "old-title",
                             "new_string": "new-title"}, "edit-title"),
        call_chunks("read", {"file_path": "note.txt"}, "read-after"),
        [TextDelta("已修改并重新读取确认"), Done("stop", {"completion_tokens": 4})],
    )

    async def scenario():
        """模型/工具在后台运行，WS 收包持续可用。"""
        service = LoopService(pg_case.factory, dependency_builder=builder_for(pg_case, tmp_path, adapter))
        connections = []
        try:
            owner_ws, owner, owner_task = await open_ws(service, pg_case.user_id, sid)
            connections.append((owner_ws, owner_task))
            submit = make_command(sid, data={"client_message_id": str(uuid4()), "content": "修正标题"})
            await owner_ws.incoming.put(submit.model_dump_json())
            await wait_for(lambda: current_card(pg_case, sid) is not None)
            card = current_card(pg_case, sid)
            assert file.read_text(encoding="utf-8").startswith("old-title")
            observer_ws, observer, observer_task = await open_ws(service, pg_case.observer_id, sid)
            connections.append((observer_ws, observer_task))
            await wait_for(lambda: any(f["type"] == "approval.requested" for f in observer_ws.sent))
            private = next(f for f in observer_ws.sent if f["type"] == "approval.requested")
            assert private["data"] == {"restricted": True}
            assert card["nonce"] not in json.dumps(observer_ws.sent)
            assert not (await service.authorize(pg_case.observer_id, sid)).trace
            trace_request = make_command(sid, "trace.subscribe")
            await observer_ws.incoming.put(trace_request.model_dump_json())
            await wait_for(lambda: any(f.get("request_id") == trace_request.request_id
                                      and f["type"] == "command.rejected" for f in observer_ws.sent))
            assert not any(f["type"].startswith("trace.") for f in observer_ws.sent)

            # 即使协作者在测试中知道 nonce，真实服务仍必须拒绝跨 actor 决定。
            with pytest.raises(AppError):
                await service.execute_command(
                    pg_case.observer_id, observer.connection_id, approval_command(sid, card),
                )
            wrong = approval_command(sid, card, nonce="wrong-nonce")
            await owner_ws.incoming.put(wrong.model_dump_json())
            await wait_for(lambda: any(f.get("request_id") == wrong.request_id and
                                      f["type"] == "command.rejected" for f in owner_ws.sent))
            assert current_card(pg_case, sid).get("response") is None
            assert file.read_text(encoding="utf-8").startswith("old-title")
            accepted = approval_command(sid, card)
            await owner_ws.incoming.put(accepted.model_dump_json())
            await wait_for(lambda: any(f["type"] == "turn.end" for f in owner_ws.sent))
            await service.entries[sid].runtime.wait()
            end = next(f for f in owner_ws.sent if f["type"] == "turn.end")
            assert end["data"]["reason"] == "completed"
            assert file.read_text(encoding="utf-8") == "new-title\nuntouched-sentinel\n"
            assert len(adapter.requests) == 4

            facts = SessionLog(sid, pg_case.factory).read()
            results = [e for e in facts if e["type"] == "tool/result"]
            assert [e["data"]["status"] for e in results] == ["succeeded"] * 3
            for index, result in enumerate(results, 1):
                message = adapter.requests[index].messages[-1]
                assert message["role"] == "tool"
                assert message["tool_call_id"] == result["data"]["call_id"]
                assert message["content"] == result["data"]["content"]
            assert "old-title" in results[0]["data"]["content"]
            assert "new-title" in results[2]["data"]["content"]
            assert "untouched-sentinel" in results[2]["data"]["content"]
            assert len([e for e in facts if e["type"] == "user/message"]) == 1
            assert current_card(pg_case, sid) is None
            resolved = next(e for e in owner_ws.sent if e["type"] == "approval.resolved")
            assert resolved["data"]["decision"] == "allow"

            # 提交后的重复审批只取回原回执，不再执行 edit。
            old = await service.execute_command(pg_case.user_id, owner.connection_id, accepted)
            assert old.data["interaction_id"] == card["interaction_id"]
            assert len(adapter.requests) == 4
            stream = SessionLog(sid, pg_case.factory).stream()
            assert [f["cursor"] for f in stream] == list(range(1, len(stream) + 1))
            assert all("projection_kind" not in f for f in stream)
            assert [e["seq"] for e in facts] == list(range(len(facts)))
            sent_cursors = [f["cursor"] for f in owner_ws.sent if "cursor" in f]
            assert sent_cursors == [f["cursor"] for f in stream]
            snapshot = await service.snapshot(pg_case.user_id, sid)
            assert snapshot.cursor == len(stream) and snapshot.state["active_turn"] is None
            assert len(snapshot.state["tools"]) == 3
            assert len(snapshot.state["assistants"]) == 4
            assert [m["role"] for m in snapshot.state["messages"]] == ["user"] + ["assistant"] * 4
            with pg_case.factory() as db:
                guards = db.scalars(select(WorkspaceExecutionGuard).where(
                    WorkspaceExecutionGuard.session_id == sid,
                )).all()
                assert len(guards) == 3 and all(g.status == "released" for g in guards)
                assert len(db.scalars(select(Message).where(Message.session_id == sid,
                                                           Message.role == "user")).all()) == 1
        finally:
            for socket, task in reversed(connections):
                await close_ws(socket, task)
            await service.close()
        assert adapter.closed
    asyncio.run(scenario())


def test_pg_command_idempotence_survives_new_service_and_changed_input_rejected(pg_case, tmp_path, monkeypatch):
    """命令/消息 ID 在新服务实例中仍幂等，未配置模型也可取回既有接受结果。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    sid = pg_case.session()
    adapter = ScriptedAdapter([TextDelta("done"), Done("stop")])
    original = make_command(sid, data={"client_message_id": str(uuid4()), "content": "hello"})

    async def scenario():
        """显式关闭第一服务释放真实 PG writer，再启动第二服务。"""
        service = LoopService(pg_case.factory, dependency_builder=builder_for(pg_case, tmp_path, adapter))
        try:
            receipt = await service.execute_command(pg_case.user_id, "connection-one", original)
            await service.entries[sid].runtime.wait()
            repeated = await service.execute_command(pg_case.user_id, "connection-two", original)
            assert repeated == receipt and len(adapter.requests) == 1
            other_request = make_command(sid, data=original.data)
            assert (await service.execute_command(pg_case.user_id, "connection-two", other_request)).data == receipt.data
            changed = make_command(sid, data={**original.data, "content": "different"},
                                   request_id=original.request_id)
            with pytest.raises(AppError):
                await service.execute_command(pg_case.user_id, "connection-one", changed)
        finally:
            await service.close()
        reopened = LoopService(pg_case.factory)
        try:
            assert await reopened.execute_command(pg_case.user_id, "new-connection", original) == receipt
            assert reopened.entries == {}
            events = SessionLog(sid, pg_case.factory).read()
            assert len([e for e in events if e["type"] == "turn/start"]) == 1
        finally:
            await reopened.close()
    asyncio.run(scenario())


def test_pg_observer_disconnect_does_not_cancel_but_owner_cancel_settles(pg_case, tmp_path, monkeypatch):
    """取消经过持久取消事实与真实 Runtime drain；旁观断连不得影响模型流。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    sid = pg_case.session(team=True)
    adapter = BlockingAdapter()

    async def scenario():
        """真实 WS 与服务后台模型并行，先退订观察者再取消指定回合。"""
        service = LoopService(pg_case.factory, dependency_builder=builder_for(pg_case, tmp_path, adapter))
        owner_ws = owner_task = None
        try:
            owner_ws, owner, owner_task = await open_ws(service, pg_case.user_id, sid)
            submit = make_command(sid, data={"client_message_id": str(uuid4()), "content": "等待取消"})
            receipt = await service.execute_command(pg_case.user_id, owner.connection_id, submit)
            await asyncio.wait_for(adapter.started.wait(), 5)
            observer_ws, _, observer_task = await open_ws(service, pg_case.observer_id, sid)
            await close_ws(observer_ws, observer_task)
            assert service.entries[sid].runtime.running and not adapter.stopped.is_set()
            with pytest.raises(AppError):
                await service.execute_command(pg_case.user_id, owner.connection_id,
                                              make_command(sid, "turn.cancel", {"turn_id": f"{sid}:999"}))
            cancelled = make_command(sid, "turn.cancel", {"turn_id": receipt.data["turn_id"]})
            await owner_ws.incoming.put(cancelled.model_dump_json())
            await wait_for(lambda: any(f["type"] == "turn.end" for f in owner_ws.sent))
            await service.entries[sid].runtime.wait()
            assert adapter.stopped.is_set()
            events = SessionLog(sid, pg_case.factory).read()
            assert [e["data"]["reason"] for e in events if e["type"] == "turn/end"] == ["cancelled"]
            assert len([e for e in events if e["type"] == "runtime/cancel_requested"]) == 1
            assert derive_messages(events)[-1]["content"] == "已提交前缀"
            before = len(events)
            await service.execute_command(pg_case.user_id, owner.connection_id, cancelled)
            assert len(SessionLog(sid, pg_case.factory).read()) == before
        finally:
            if owner_ws is not None:
                await close_ws(owner_ws, owner_task)
            await service.close()
    asyncio.run(scenario())


def test_pg_cancel_during_real_native_read_waits_for_guard_settlement(pg_case, tmp_path, monkeypatch):
    """线程中真实读取完成前不可释放 guard；取消后不再请求第二轮模型。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    sid = pg_case.session()
    (tmp_path / "read.txt").write_text("actual-file-body", encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    original_registry = build_default_registry()
    definition = original_registry.get("read")

    def delayed_read(arguments, sandbox_dir, context=None):
        """仅延迟原 handler 的开始，不伪造输出或改变原生文件执行。"""
        entered.set()
        if not release.wait(5):
            raise TimeoutError("测试未放行原生读取")
        return definition.handler(arguments, sandbox_dir, context)

    registry = ToolRegistry()
    registry.register(replace(definition, handler=delayed_read))
    registry.register(original_registry.get("edit"))
    adapter = ScriptedAdapter(call_chunks("read", {"file_path": "read.txt"}, "slow-read"))

    async def scenario():
        """取消从真实服务进入 Runtime，再由 Bridge join 原生线程完成结算。"""
        service = LoopService(pg_case.factory, dependency_builder=builder_for(
            pg_case, tmp_path, adapter, registry=registry,
        ))
        try:
            receipt = await service.execute_command(pg_case.user_id, "owner", make_command(
                sid, data={"client_message_id": str(uuid4()), "content": "read and cancel"},
            ))
            await wait_for(entered.is_set)
            await service.execute_command(pg_case.user_id, "owner", make_command(
                sid, "turn.cancel", {"turn_id": receipt.data["turn_id"]},
            ))
            with pg_case.factory() as db:
                guard = db.scalar(select(WorkspaceExecutionGuard).where(
                    WorkspaceExecutionGuard.session_id == sid,
                ))
                assert guard.status == "active"
            assert service.entries[sid].runtime.running
            release.set()
            await asyncio.wait_for(service.entries[sid].runtime.wait(), 5)
            facts = SessionLog(sid, pg_case.factory).read()
            results = [e for e in facts if e["type"] == "tool/result"]
            assert len(results) == 1
            assert results[0]["data"]["status"] == "succeeded"
            assert "actual-file-body" in results[0]["data"]["content"]
            assert [e["data"]["reason"] for e in facts if e["type"] == "turn/end"] == ["cancelled"]
            assert len(adapter.requests) == 1
            with pg_case.factory() as db:
                guard = db.scalar(select(WorkspaceExecutionGuard).where(
                    WorkspaceExecutionGuard.session_id == sid,
                ))
                assert guard.status == "released"
        finally:
            release.set()
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("decision", ["deny", "cancel"])
def test_pg_denied_or_cancelled_approval_never_edits(pg_case, tmp_path, monkeypatch, decision):
    """拒绝和等待中取消都不跨文件副作用边界，卡终态必须与工具结果落库。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    sid = pg_case.session()
    target = tmp_path / "denied.txt"
    target.write_text("old", encoding="utf-8")
    adapter = ScriptedAdapter(
        call_chunks("edit", {"file_path": "denied.txt", "old_string": "old",
                             "new_string": "new"}, "must-not-edit"),
        [TextDelta("操作未获批准"), Done("stop")],
    )

    async def scenario():
        """服务校验回执后由真实调度器结算，不直接写 tool/result 伪造结果。"""
        service = LoopService(pg_case.factory, dependency_builder=builder_for(pg_case, tmp_path, adapter))
        try:
            receipt = await service.execute_command(pg_case.user_id, "owner", make_command(
                sid, data={"client_message_id": str(uuid4()), "content": "edit"},
            ))
            await wait_for(lambda: current_card(pg_case, sid) is not None)
            card = current_card(pg_case, sid)
            if decision == "deny":
                await service.execute_command(pg_case.user_id, "owner", approval_command(
                    sid, card, decision="deny",
                ))
            else:
                await service.execute_command(pg_case.user_id, "owner", make_command(
                    sid, "turn.cancel", {"turn_id": receipt.data["turn_id"]},
                ))
            await asyncio.wait_for(service.entries[sid].runtime.wait(), 5)
            facts = SessionLog(sid, pg_case.factory).read()
            assert not any(e["type"] == "tool/dispatch" for e in facts)
            results = [e for e in facts if e["type"] == "tool/result"]
            assert len(results) == 1 and results[0]["data"]["status"] != "succeeded"
            assert target.read_text(encoding="utf-8") == "old"
            assert current_card(pg_case, sid) is None
            resolved = next(f for f in SessionLog(sid, pg_case.factory).stream()
                            if f["type"] == "approval.resolved")
            assert resolved["data"]["decision"] == ("deny" if decision == "deny" else "cancelled")
            if decision == "deny":
                assert adapter.requests[1].messages[-1]["content"] == results[0]["data"]["content"]
        finally:
            await service.close()
    asyncio.run(scenario())


def test_pg_expired_nonce_cannot_authorize_edit(pg_case, tmp_path, monkeypatch):
    """即使持久卡仍存在、nonce 正确，过期回执也不能执行工具或消费合法决定。"""
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    sid = pg_case.session()
    target = tmp_path / "expired.txt"
    target.write_text("old", encoding="utf-8")
    adapter = ScriptedAdapter(call_chunks("edit", {
        "file_path": "expired.txt", "old_string": "old", "new_string": "new",
    }, "expired-edit"))

    async def scenario():
        """只调整测试卡 TTL 以避免等待生产超时，其他授权与执行路径均真实。"""
        service = LoopService(pg_case.factory, dependency_builder=builder_for(pg_case, tmp_path, adapter))
        try:
            await service.execute_command(pg_case.user_id, "owner", make_command(sid, data={
                "client_message_id": str(uuid4()), "content": "edit",
            }))
            await wait_for(lambda: current_card(pg_case, sid) is not None)
            card = current_card(pg_case, sid)
            with pg_case.factory.begin() as db:
                session = db.get(Session, sid)
                session.pending_confirm = {**session.pending_confirm, "expires_at": 1.0}
            command = approval_command(sid, card)
            with pytest.raises(AppError) as error:
                await service.execute_command(pg_case.user_id, "owner", command)
            assert error.value.code == ErrorCode.CONCURRENCY
            assert SessionLog(sid, pg_case.factory).command_receipt(pg_case.user_id, command.request_id) is None
            assert target.read_text(encoding="utf-8") == "old"
            assert not any(e["type"] == "tool/dispatch" for e in SessionLog(sid, pg_case.factory).read())
        finally:
            await service.close()
        assert current_card(pg_case, sid) is None
    asyncio.run(scenario())


def test_pg_restart_recovers_unknown_tool_once_without_reexecuting(pg_case, tmp_path):
    """模拟进程在 dispatch 后消失；新 Runtime 只结算未知结果，不重做文件编辑。"""
    sid = pg_case.session()
    target = tmp_path / "state.txt"
    target.write_text("unchanged", encoding="utf-8")
    log = SessionLog(sid, pg_case.factory, actor_id=pg_case.user_id)
    log.claim()
    try:
        log.append("turn/start", {"turn": 1})
        log.append("user/message", {"turn": 1, "content": "edit"})
        log.append("step/start", {"turn": 1, "step": 1})
        call = {"id": "c", "name": "edit", "args": {
            "file_path": "state.txt", "old_string": "unchanged", "new_string": "changed",
        }}
        base = {"turn": 1, "step": 1, "attempt_id": "a", "call_id": "c", "name": "edit"}
        log.append("assistant/message", {
            **base, "message": {"role": "assistant", "content": "", "tool_calls": [call]},
            "content": "", "tool_calls": [call],
        })
        declared = log.append("tool/call", {**base, **call})
        log.append("tool/dispatch", {
            **base, "call_seq": declared["seq"], "execution_id": str(uuid4()),
            "scope_path": str(tmp_path.resolve()), "access": "write",
        })
    finally:
        # 释放连接模拟进程消失，不调用 graceful Runtime.close 去提前结算。
        log.close()

    async def scenario():
        """新图只调用 recover，不提供能够执行文件的模型或 scheduler。"""
        reopened = SessionLog(sid, pg_case.factory, actor_id=pg_case.user_id)
        reopened.claim()
        runtime = AgentRuntime(reopened, await build_agent(LoopSettings()))
        try:
            await runtime.recover()
            events = reopened.read()
            repaired = [e for e in events if e["type"] == "tool/result"]
            assert len(repaired) == 1 and repaired[0]["data"]["status"] == "outcome_unknown"
            assert repaired[0]["data"]["synthetic"]
            assert events[-1]["type"] == "turn/end" and events[-1]["data"]["reason"] == "interrupted"
            assert target.read_text(encoding="utf-8") == "unchanged"
            assert derive_messages(events)[-1]["role"] == "tool"
            await runtime.recover()
            assert reopened.read() == events
            with pg_case.factory() as db:
                guard = db.scalar(select(WorkspaceExecutionGuard).where(
                    WorkspaceExecutionGuard.session_id == sid,
                ))
                assert guard.status == "quarantined"
        finally:
            await runtime.close()
            reopened.close()
    asyncio.run(scenario())
