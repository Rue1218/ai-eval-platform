"""注入服务的 WS 集成回归；模拟已提交存储，不调用真实模型或生产数据库。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.agent.events import frame
from app.errors import AppError, ErrorCode
from app.routers.ws_v2 import (
    CommandReceipt,
    StreamSnapshot,
    WsAccess,
    WsV2Connection,
    agent_websocket_v2,
)
from tests.test_loop_ws_protocol import command, fact


class FakeSocket:
    """可驱动完整 handler 的异步传输，显式记录发送和关闭结果。"""

    def __init__(self, service=None, ticket="ticket"):
        """保留应用注入形状，不依赖 main.py 接线。"""
        self.app = SimpleNamespace(state=SimpleNamespace(loop_service=service))
        self.query_params = {"ticket": ticket} if ticket else {}
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = None
        self.accepted = False

    async def accept(self):
        """记录握手。"""
        self.accepted = True

    async def receive_text(self):
        """None 模拟网络断开。"""
        value = await self.incoming.get()
        if value is None:
            raise WebSocketDisconnect()
        return value

    async def send_json(self, value):
        """独立副本模拟网络序列化。"""
        self.sent.append(json.loads(json.dumps(value)))

    async def close(self, code, reason=""):
        """关闭同时唤醒收包循环。"""
        self.closed = code
        await self.incoming.put(None)

    async def push(self, kind="subscribe", data=None, **extra):
        """客户端命令不包含 actor。"""
        await self.incoming.put(json.dumps(command(kind, data, **extra)))


class FakeService:
    """事务服务替身：回执存储跨连接共享，用于验证 WS 不重复执行副作用。"""

    def __init__(self):
        """测试状态与 socket 生命周期分离，模拟持久幂等结果。"""
        self.tickets = set()
        self.access = WsAccess(write=True)
        self.visible = True
        self.rows = []
        self.facts = [fact("session/start")]
        self.receipts = {}
        self.messages = {}
        self.effects = 0
        self.cancelled = 0
        self.owner = None
        self.attachments = {}
        self.detached = []
        self.earliest = 1
        self.calls = []
        self.fail_execute = False

    async def authenticate(self, ticket):
        """模拟一次性票据；返回服务端固定 actor。"""
        if ticket in self.tickets or ticket == "invalid":
            raise AppError(ErrorCode.UNAUTHORIZED, "private token detail")
        self.tickets.add(ticket)
        return "server-actor"

    async def authorize(self, actor_id, session_id):
        """权限变更即时影响下一次读取/发送。"""
        assert actor_id == "server-actor"
        if not self.visible or session_id != "s":
            raise AppError(ErrorCode.NOT_FOUND, "hidden")
        return self.access

    async def attach(self, actor_id, session_id, connection_id, on_transient):
        """观察订阅不得启动回合或 claim writer。"""
        self.attachments[connection_id] = on_transient

    async def snapshot(self, actor_id, session_id):
        """读取绑定高水位的状态，仅供恢复，不执行任何命令。"""
        assert self.attachments
        high = max((row["cursor"] for row in self.rows), default=0)
        return StreamSnapshot(high, self.earliest, {"at_cursor": high})

    async def read_stream(self, session_id, after_cursor, limit):
        """模拟排序分页，存储是唯一持久实时来源。"""
        return [row for row in self.rows if row["cursor"] > after_cursor][:limit]

    async def read_trace(self, session_id, after_seq, limit):
        """从 seq=0 的事实读取诊断。"""
        return [row for row in self.facts if row["seq"] > after_seq][:limit]

    async def execute_command(self, actor_id, connection_id, value):
        """模拟原子接受：去重发生在服务，不在连接缓存中。"""
        if self.fail_execute:
            raise RuntimeError("SQL password=private-secret")
        self.calls.append((actor_id, connection_id, value))
        key = (actor_id, value.session_id, value.request_id)
        if key in self.receipts:
            fingerprint, receipt = self.receipts[key]
            if fingerprint != value.fingerprint:
                raise AppError(ErrorCode.VALIDATION, "same id different input")
            return receipt
        if value.type == "turn.submit":
            message = value.data["client_message_id"]
            if message in self.messages:
                receipt = self.messages[message]
            else:
                if self.owner is not None:
                    raise AppError(ErrorCode.CONCURRENCY, "busy")
                self.effects += 1
                self.owner = connection_id
                receipt = CommandReceipt({"turn_id": "t"}, {"turn_id": "t", "source_seq": 0})
                self.messages[message] = receipt
        elif value.type == "turn.cancel":
            if value.data["turn_id"] != "t" or connection_id != self.owner:
                raise AppError(ErrorCode.CONCURRENCY, "stale turn or non controller")
            self.cancelled += 1
            self.owner = None
            receipt = CommandReceipt({"turn_id": "t"})
        else:
            receipt = CommandReceipt({"interaction_id": value.data["interaction_id"]})
        self.receipts[key] = (value.fingerprint, receipt)
        return receipt

    async def detach(self, actor_id, session_id, connection_id):
        """只取消实际控制连接，旁观者注销无副作用。"""
        self.detached.append(connection_id)
        self.attachments.pop(connection_id, None)
        if self.owner == connection_id:
            self.cancelled += 1
            self.owner = None


async def until(predicate):
    """等待有限测试条件，失败不无限挂住 pytest。"""
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


async def connect(service, *, subscribe=True, **kwargs):
    """建立可直接测试限额的连接并完成回放边界。"""
    socket = FakeSocket(service)
    connection = WsV2Connection(socket, service, "server-actor", poll_interval=0.001, **kwargs)
    task = asyncio.create_task(connection.run())
    if subscribe:
        await socket.push()
        await until(lambda: any(f["type"] == "replay.completed" for f in socket.sent))
    return socket, connection, task


async def disconnect(socket, task):
    """测试结束等待连接清理，不等待模型回合。"""
    await socket.incoming.put(None)
    await asyncio.wait_for(task, 2)


def test_ticket_authentication_and_missing_service():
    """入口缺依赖关闭 1013；无效、重复票关闭 4401，绝不信任客户端 actor。"""
    async def scenario():
        """依次驱动独立握手。"""
        service = FakeService()
        for socket, code in [
            (FakeSocket(), 1013),
            (FakeSocket(service, ticket=""), 4401),
            (FakeSocket(service, ticket="invalid"), 4401),
        ]:
            await agent_websocket_v2(socket)
            assert socket.closed == code and not socket.accepted
        first = FakeSocket(service)
        await first.incoming.put(None)
        await agent_websocket_v2(first)
        assert first.accepted
        again = FakeSocket(service)
        await agent_websocket_v2(again)
        assert again.closed == 4401
    asyncio.run(scenario())


def test_command_requires_subscription_and_replay_has_no_effects():
    """回放和快照读取永不创建用户消息、启动工具或抢占控制权。"""
    async def scenario():
        """持久事件重放只发下行。"""
        service = FakeService()
        service.rows = [
            frame("turn.start", {}, session_id="s", cursor=1),
            frame("turn.end", {"reason": "completed"}, session_id="s", cursor=2),
        ]
        socket, connection, task = await connect(service)
        assert [f["cursor"] for f in socket.sent if "cursor" in f] == [1, 2]
        assert service.effects == 0 and service.owner is None
        assert connection.ready
        await disconnect(socket, task)
    asyncio.run(scenario())


def test_replay_boundary_precedes_new_rows_and_duplicates_are_ignored():
    """快照后追加行不能越过 replay.completed，高水位与实时流严格衔接。"""
    async def scenario():
        """在快照读取后注入新事务，复现回放/实时竞争。"""
        service = FakeService()
        service.rows = [frame("turn.start", {}, session_id="s", cursor=1)]
        original = service.snapshot

        async def racing_snapshot(*args):
            """高水位取 1 后新提交 2。"""
            result = await original(*args)
            service.rows.append(frame("step.start", {}, session_id="s", cursor=2))
            return result

        service.snapshot = racing_snapshot
        socket, _, task = await connect(service)
        await until(lambda: any(f.get("cursor") == 2 for f in socket.sent))
        types = [f["type"] for f in socket.sent]
        assert types.index("turn.start") < types.index("replay.completed") < types.index("step.start")
        assert [f["cursor"] for f in socket.sent if "cursor" in f] == [1, 2]
        await disconnect(socket, task)
    asyncio.run(scenario())


@pytest.mark.parametrize("after,earliest", [(99, 1), (0, 3)])
def test_bad_cursor_produces_bound_snapshot_and_blocks_mutations(after, earliest):
    """无效或过期游标不能自动归零重放，更不能执行输入副作用。"""
    async def scenario():
        """等待重同步帧后检查禁写。"""
        service = FakeService()
        service.rows = [frame("turn.start", {}, session_id="s", cursor=3)]
        service.earliest = earliest
        socket, connection, task = await connect(service, subscribe=False)
        await socket.push(data={"after_cursor": after})
        await until(lambda: any(f["type"] == "resync.required" for f in socket.sent))
        resync = next(f for f in socket.sent if f["type"] == "resync.required")
        assert resync["data"] == {"cursor": 3, "snapshot": {"at_cursor": 3}}
        assert not connection.ready and service.effects == 0
        await socket.push("turn.submit", {"client_message_id": "m", "content": "x"})
        await until(lambda: any(f["type"] == "command.rejected" for f in socket.sent))
        assert service.effects == 0
        await disconnect(socket, task)
    asyncio.run(scenario())


def test_live_gap_cannot_advance_cursor():
    """实时流遇到缺号必须重同步，不能吞掉缺失事件。"""
    async def scenario():
        """故意让持久服务返回不连续序号。"""
        service = FakeService()
        socket, connection, task = await connect(service)
        service.rows.append(frame("step.start", {}, session_id="s", cursor=2))
        await until(lambda: any(f["type"] == "resync.required" for f in socket.sent))
        assert not connection.ready
        assert not any(f.get("cursor") == 2 for f in socket.sent)
        await disconnect(socket, task)
    asyncio.run(scenario())


def test_idempotence_survives_connections_and_old_cancel_is_rejected():
    """服务存储幂等结果跨连接重用，重试不抢控制权，旧取消不能命中新回合。"""
    async def scenario():
        """并行控制者和观察者验证命令与断连边界。"""
        service = FakeService()
        first, owner, first_task = await connect(service)
        payload = {"client_message_id": "m", "content": "run"}
        await first.push("turn.submit", payload, request_id="submit")
        await until(lambda: service.effects == 1)
        second, observer, second_task = await connect(service)
        await second.push("turn.submit", payload, request_id="submit")
        await until(lambda: any(f["type"] == "command.accepted" for f in second.sent))
        assert service.effects == 1 and service.owner == owner.connection_id
        assert service.calls[-1][0] == "server-actor"
        await second.push("turn.submit", {**payload, "content": "changed"}, request_id="submit")
        await second.push("turn.cancel", {"turn_id": "stale"}, request_id="cancel")
        await until(lambda: sum(f["type"] == "command.rejected" for f in second.sent) == 2)
        await disconnect(second, second_task)
        assert observer.connection_id in service.detached and service.cancelled == 0
        # 接收仍可响应 ping，证明 WS 没有等待运行中的整轮。
        await first.push("ping", {}, request_id="ping")
        await until(lambda: any(f["type"] == "pong" for f in first.sent))
        await disconnect(first, first_task)
        assert service.cancelled == 1
    asyncio.run(scenario())


def test_trace_permission_is_independent_and_seq_zero_replays():
    """写权限不自动授予 trace；单独授权后可读 seq=0，撤权即时停止。"""
    async def scenario():
        """trace 和语义队列保持编号及 ACL 独立。"""
        service = FakeService()
        socket, connection, task = await connect(service)
        await socket.push("trace.subscribe", {}, request_id="trace1")
        await until(lambda: any(f["type"] == "command.rejected" for f in socket.sent))
        assert not any(f["type"] == "trace.event" for f in socket.sent)
        service.access = WsAccess(write=True, trace=True)
        await socket.push("trace.subscribe", {}, request_id="trace2")
        await until(lambda: any(f["type"] == "trace.event" for f in socket.sent))
        trace = next(f for f in socket.sent if f["type"] == "trace.event")
        assert trace["data"]["event"]["seq"] == 0 and "cursor" not in trace
        service.access = WsAccess(write=True)
        service.facts.append(fact("user/message", seq=1, content="hidden"))
        await until(lambda: not connection.trace_enabled)
        assert not any(f["type"] == "trace.event" and
                       f["data"]["event"]["seq"] == 1 for f in socket.sent)
        service.visible = False
        await asyncio.wait_for(task, 2)
        assert socket.closed == 4404
    asyncio.run(scenario())


def test_output_acl_is_checked_at_send_time_and_errors_are_sanitized():
    """排队之后撤权限仍安全占位，内部异常不回显数据库内容。"""
    async def scenario():
        """交互与故障均经接收者隔离出口。"""
        service = FakeService()
        socket, connection, task = await connect(service)
        connection.enqueue(frame(
            "approval.requested", {"interaction_id": "i", "nonce": "n"},
            session_id="s", cursor=1,
        ))
        await until(lambda: any(f["type"] == "approval.requested" for f in socket.sent))
        card = next(f for f in socket.sent if f["type"] == "approval.requested")
        assert card["data"] == {"restricted": True} and card["cursor"] == 1
        service.fail_execute = True
        await socket.push("turn.submit", {"client_message_id": "m", "content": "x"})
        await until(lambda: any(f["type"] == "command.rejected" for f in socket.sent))
        assert "private-secret" not in json.dumps(socket.sent)
        await disconnect(socket, task)
    asyncio.run(scenario())


def test_command_rejection_exposes_safe_actionable_reason():
    """并发拒绝应让浏览器可重试，不能退回模糊的权限/输入提示。"""
    async def scenario():
        """先占用回合，再验证第二次提交得到固定安全说明。"""
        service = FakeService()
        socket, _, task = await connect(service)
        await socket.push(
            "turn.submit", {"client_message_id": "first", "content": "x"}, request_id="first"
        )
        await until(lambda: service.effects == 1)
        await socket.push(
            "turn.submit", {"client_message_id": "second", "content": "y"}, request_id="second"
        )
        await until(lambda: any(f["type"] == "command.rejected" for f in socket.sent))
        rejected = next(f for f in socket.sent if f["type"] == "command.rejected")
        assert rejected["data"] == {
            "code": "CONCURRENCY",
            "message": "上一轮仍在收尾或会话正被占用，请稍后重试",
        }
        await disconnect(socket, task)
    asyncio.run(scenario())


def test_backpressure_drops_transient_then_closes_persistent_overflow():
    """有界队列先丢瞬态；仍超限则断连，让持久事件从数据库回放。"""
    async def scenario():
        """直接验证同步发布不等待网络。"""
        connection = WsV2Connection(FakeSocket(), FakeService(), "server-actor", queue_size=2)
        connection.enqueue(frame("assistant.text.delta", {"text": "a"}, session_id="s"))
        connection.enqueue(frame("assistant.text.delta", {"text": "b"}, session_id="s"))
        connection.enqueue(frame("turn.start", {}, session_id="s", cursor=1))
        assert connection.queue.qsize() == 1 and not connection.slow.is_set()
        connection.enqueue(frame("turn.end", {"reason": "completed"}, session_id="s", cursor=2))
        connection.enqueue(frame("step.end", {}, session_id="s", cursor=3))
        assert connection.slow.is_set() and connection.queue.qsize() == 2
    asyncio.run(scenario())


def test_send_timeout_cancels_controller_and_releases_subscription():
    """慢连接即使阻塞发送也必须触发控制者取消和资源回收。"""
    async def scenario():
        """握手后阻塞真实发送出口。"""
        service = FakeService()
        socket, connection, task = await connect(service, send_timeout=0.02)
        service.owner = connection.connection_id

        async def blocked(_):
            """模拟永不完成的网络发送。"""
            await asyncio.Event().wait()

        socket.send_json = blocked
        connection.control("pong", {})
        await asyncio.wait_for(task, 2)
        assert socket.closed == 4408 and service.cancelled == 1
        assert not service.attachments
    asyncio.run(scenario())
