"""独立 WS v2 入口；数据库、运行时和命令事务由注入的 LoopService 负责。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.agent.events import (
    event_schema_catalog,
    event_schema_catalog_etag,
    frame,
    schema_catalog,
    trace_frame,
    visible_frame,
)
from app.errors import AppError, ErrorCode

router = APIRouter()
logger = logging.getLogger(__name__)
Id = Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=True)]
Cursor = Annotated[int, Field(ge=0)]
MAX_FRAME_BYTES = 65536


class StrictData(BaseModel):
    """拒绝未知字段与类型强转，避免身份/配置通过透传字典注入。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class Subscribe(StrictData):
    """语义订阅使用独立会话游标。"""

    after_cursor: Cursor = 0
    view: Literal["semantic"] = "semantic"


class Submit(StrictData):
    """附件与协议档只接受平台对象 ID；服务端重新解析权限与模型配置。"""

    client_message_id: Id
    content: Annotated[str, StringConstraints(min_length=1, max_length=60000)]
    attachment_refs: list[Id] = Field(default_factory=list, max_length=32)
    profile_id: Id | None = None
    reasoning_effort: Literal["off", "low", "medium", "high", "xhigh", "max"] | None = None


class Cancel(StrictData):
    """取消必须指向具体回合，不能误取消后来启动的回合。"""

    turn_id: Id


class Interaction(StrictData):
    """交互回执绑定完整执行身份，nonce 的消费由事务完成。"""

    interaction_id: Id
    turn_id: Id
    turn: Annotated[int, Field(ge=1)]
    attempt_id: Id
    call_id: Id
    nonce: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class Approval(Interaction):
    """工具审批的三种选择。"""

    decision: Literal["allow", "deny", "always"]


class Answer(StrictData):
    """单题回答不允许任意对象注入。"""

    question_id: Id
    answer: Annotated[str, StringConstraints(max_length=16000)] | Annotated[
        list[Annotated[str, StringConstraints(max_length=16000)]], Field(max_length=32)
    ]


class Question(Interaction):
    """完整题组交由服务与持久问题定义进一步核验。"""

    answers: list[Answer] = Field(min_length=1, max_length=32)


class TaskConfirmation(Interaction):
    """业务确认额外绑定待入队规格摘要。"""

    spec_hash: Id
    decision: Literal["confirm", "reject"]


class TraceSubscribe(StrictData):
    """轨迹序号独立于 session_stream 游标。"""

    after_seq: Annotated[int, Field(ge=-1)] = -1
    catalog_etag: Id | None = None


class Ping(StrictData):
    """客户端时钟只回显，不参与授权。"""

    client_time: Annotated[str, StringConstraints(max_length=128)] | None = None


_DATA_TYPES = {
    "subscribe": Subscribe, "unsubscribe": StrictData, "turn.submit": Submit,
    "turn.cancel": Cancel, "approval.respond": Approval, "question.respond": Question,
    "task_confirmation.respond": TaskConfirmation, "trace.subscribe": TraceSubscribe,
    "trace.unsubscribe": StrictData, "ping": Ping,
}
MUTATING_COMMANDS = frozenset({
    "turn.submit", "turn.cancel", "approval.respond", "question.respond",
    "task_confirmation.respond",
})


class Command(StrictData):
    """服务端规范命令；actor 永远来自已消费短票，不属于此结构。"""

    protocol_version: Annotated[int, Field(ge=2, le=2)]
    type: str
    request_id: Id
    session_id: Id
    data: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        """算法 v1：不含 request_id 的规范输入摘要，供持久幂等校验。"""
        encoded = json.dumps(
            {"type": self.type, "session_id": self.session_id, "data": self.data},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    """重复 JSON 字段一律拒绝，不能让解析器先后覆盖身份。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复字段")
        result[key] = value
    return result


def parse_command(raw: str) -> Command:
    """解析一帧并生成确定性的规范数据；校验原文不返回客户端。"""
    try:
        if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
            raise ValueError("帧过大")
        value = json.loads(raw, object_pairs_hook=_unique_object)
        command = Command.model_validate(value)
        model = _DATA_TYPES.get(command.type)
        if model is None:
            raise ValueError("未知命令")
        data = model.model_validate(command.data)
        command.data = data.model_dump(exclude_none=True)
        if isinstance(data, Question):
            ids = [answer.question_id for answer in data.answers]
            if len(ids) != len(set(ids)):
                raise ValueError("问题重复")
        # 即使无业务字段使用 NaN，也不接受非法 JSON 数值。
        command.fingerprint
        return command
    except (ValueError, ValidationError, TypeError, RecursionError) as exc:
        raise AppError(ErrorCode.VALIDATION, "WS v2 命令格式无效") from exc


@dataclass(frozen=True)
class WsAccess:
    """最新会话可见性已由 authorize 验证，剩余权限默认关闭。"""

    write: bool = False
    trace: bool = False
    reasoning: bool = False
    interactions: bool = False


@dataclass(frozen=True)
class StreamSnapshot:
    """同一事务时点的高水位、保留窗口与授权恢复状态。"""

    cursor: int
    earliest_cursor: int = 1
    state: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CommandReceipt:
    """仅携带已提交的接受结果，不携带 ORM、Runtime 或凭据。"""

    data: dict
    correlation: dict = field(default_factory=dict)


class LoopServiceProtocol(Protocol):
    """主 agent 的注入接口；所有方法不得等待整轮模型或执行长任务。

    execute_command 在会话行锁事务中校验幂等键/输入摘要/client_message_id，
    当前执行身份、nonce、TTL 与控制连接；提交后调用 Runtime 的快速启动/
    取消入口并返回既有或新回执。attach 可在已取得释放写锁时结算硬重启
    遗留回合，但不抢占存活控制权；detach 仅取消实际属于该 connection_id
    的回合。失败抛 AppError，不返回异常原文。
    """

    async def authenticate(self, ticket: str) -> str:
        """复用单次票据、用户禁用与 auth_version 校验，返回 actor ID。"""
        ...

    async def authorize(self, actor_id: str, session_id: str) -> WsAccess:
        """实时验证 ACL 与 agent_loop_v2 引擎；不可见抛 NOT_FOUND。"""
        ...

    async def attach(
        self, actor_id: str, session_id: str, connection_id: str,
        on_transient: Callable[[dict], None],
    ) -> None:
        """先注册瞬态回调；回调只接收完整 transient 信封，不等待网络。"""
        ...

    async def snapshot(self, actor_id: str, session_id: str) -> StreamSnapshot:
        """返回同一高水位对应的授权快照。"""
        ...

    async def read_stream(self, session_id: str, after_cursor: int, limit: int) -> list[dict]:
        """读取排序的已提交持久信封，不能跨会话或跳过已提交游标。"""
        ...

    async def read_trace(self, session_id: str, after_seq: int, limit: int) -> list[dict]:
        """读取排序的规范事实；传输层再次按 trace ACL 脱敏。"""
        ...

    async def execute_command(
        self, actor_id: str, connection_id: str, command: Command,
    ) -> CommandReceipt:
        """原子幂等接受并立即返回，不 wait Runtime 的整轮后台任务。"""
        ...

    async def detach(self, actor_id: str, session_id: str, connection_id: str) -> None:
        """注销并仅取消实际控制者持有的回合；可安全重复调用。"""
        ...


class WsV2Connection:
    """每连接独立接收、发送与读取流；有界队列不反压 Runtime 写事实。"""

    def __init__(
        self, websocket: WebSocket, service: LoopServiceProtocol, actor_id: str, *,
        queue_size: int = 128, page_size: int = 64, poll_interval: float = 0.1,
        send_timeout: float = 10,
    ):
        """注入可测试的传输限额，生产使用固定保守默认值。"""
        self.ws, self.service, self.actor_id = websocket, service, actor_id
        self.connection_id = uuid4().hex
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_size)
        self.page_size, self.poll_interval = page_size, poll_interval
        self.send_timeout = send_timeout
        self.slow = asyncio.Event()
        self.session_id: str | None = None
        self.ready = False
        self.trace_enabled = False
        self.trace_seq = -1
        self.trace_history = True
        self.pump: asyncio.Task | None = None
        self.loop = asyncio.get_running_loop()

    def enqueue(self, envelope: dict) -> None:
        """队满先丢瞬态；持久与控制帧无法入队则明确断开待回放。"""
        if self.slow.is_set():
            return
        if self.queue.full():
            if envelope["durability"] == "transient":
                return
            retained = []
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item["durability"] != "transient":
                    retained.append(item)
            for item in retained:
                self.queue.put_nowait(item)
            if self.queue.full():
                self.slow.set()
                return
        self.queue.put_nowait(envelope)

    def on_transient(self, envelope: dict) -> None:
        """跨线程发布安全，回放期不拼接未提交增量。"""
        def publish() -> None:
            """在连接所属事件循环内检查当前订阅身份。"""
            if (
                self.ready and envelope.get("session_id") == self.session_id
                and envelope.get("durability") == "transient"
            ):
                self.enqueue(envelope)
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(publish)

    def control(self, kind: str, data: dict, request_id: str | None = None) -> None:
        """排入控制帧；控制数据始终与持久流游标独立。"""
        self.enqueue(frame(kind, data, session_id=self.session_id, request_id=request_id))

    def reject(self, code: ErrorCode, command: Command | None = None) -> None:
        """错误只用固定安全摘要，避免 AppError 意外携带上游秘密。"""
        self.control("command.rejected", {
            "code": code.value, "message": "命令未接受，请检查权限、状态或输入",
        }, command.request_id if command else None)

    async def sender(self) -> None:
        """发送前重新授权，不把原始广播帧共享给不同权限接收者。"""
        while True:
            envelope = await self.queue.get()
            sid = envelope.get("session_id")
            access = WsAccess()
            if sid is not None:
                if sid != self.session_id:
                    continue
                access = await self.service.authorize(self.actor_id, sid)
            if envelope["type"].startswith("trace."):
                if not self.trace_enabled or not access.trace:
                    continue
            outgoing = visible_frame(
                envelope, interactions=access.interactions, reasoning=access.reasoning,
            )
            if outgoing is not None:
                await asyncio.wait_for(self.ws.send_json(outgoing), self.send_timeout)

    async def stop_subscription(self) -> None:
        """先停读流，再注销控制权；旁观者 detach 不影响运行。"""
        sid, self.session_id = self.session_id, None
        self.ready = self.trace_enabled = False
        if self.pump:
            self.pump.cancel()
            with suppress(asyncio.CancelledError):
                await self.pump
            self.pump = None
        if sid:
            await self.service.detach(self.actor_id, sid, self.connection_id)

    async def subscribe(self, command: Command) -> None:
        """注册后取快照；回放独立任务让收包循环继续处理取消/判活。"""
        if self.session_id == command.session_id:
            # 同连接修复 cursor 缺口时保留 Runtime 控制权，不能 detach 误取消回合。
            self.ready = False
            if self.pump:
                self.pump.cancel()
                with suppress(asyncio.CancelledError):
                    await self.pump
            await self.service.authorize(self.actor_id, command.session_id)
            self.pump = asyncio.create_task(self.stream(command.data["after_cursor"]))
            return
        if self.session_id and self.ready:
            raise AppError(ErrorCode.CONCURRENCY, "请先退订当前会话")
        if self.session_id:
            await self.stop_subscription()
        await self.service.authorize(self.actor_id, command.session_id)
        self.session_id = command.session_id
        await self.service.attach(
            self.actor_id, command.session_id, self.connection_id, self.on_transient,
        )
        self.pump = asyncio.create_task(self.stream(command.data["after_cursor"]))

    async def stream(self, after_cursor: int) -> None:
        """只推进连续已提交前缀；快照替换后由客户端显式重新订阅。"""
        sid = self.session_id
        try:
            snapshot = await self.service.snapshot(self.actor_id, sid)
            high = snapshot.cursor
            self.control("subscribed", {"cursor": high})
            if after_cursor > high or after_cursor < snapshot.earliest_cursor - 1:
                self.control("resync.required", {"cursor": high, "snapshot": snapshot.state})
                return
            cursor = after_cursor
            replay = True
            while True:
                access = await self.service.authorize(self.actor_id, sid)
                rows = await self.service.read_stream(sid, cursor, self.page_size)
                for row in rows:
                    number = row.get("cursor")
                    if (
                        row.get("session_id") != sid or row.get("durability") != "persistent"
                        or type(number) is not int
                    ):
                        raise AppError(ErrorCode.INTERNAL, "持久流格式错误")
                    if number <= cursor:
                        continue
                    if number != cursor + 1:
                        # 缺号不得推进；重新获取绑定高水位的授权快照。
                        current = await self.service.snapshot(self.actor_id, sid)
                        self.ready = False
                        self.control("resync.required", {
                            "cursor": current.cursor, "snapshot": current.state,
                        })
                        return
                    if replay and number > high:
                        self.control("replay.completed", {"cursor": high})
                        replay, self.ready = False, True
                    self.enqueue(row)
                    cursor = number
                if replay and cursor == high:
                    self.control("replay.completed", {"cursor": high})
                    replay, self.ready = False, True
                if replay and not rows and cursor < high:
                    raise AppError(ErrorCode.INTERNAL, "快照前缀缺失")
                if self.trace_enabled and access.trace:
                    facts = await self.service.read_trace(sid, self.trace_seq, self.page_size)
                    for event in facts:
                        if type(event.get("seq")) is not int or event["seq"] <= self.trace_seq:
                            continue
                        self.enqueue(trace_frame(
                            event, sid, source="history" if self.trace_history else "runtime",
                        ))
                        self.trace_seq = event["seq"]
                    if not facts:
                        self.trace_history = False
                elif not access.trace:
                    self.trace_enabled = False
                # 读取有限页后让出调度，避免快读空转饿死接收/发送任务。
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            raise
        except AppError as exc:
            await self.ws.close(code=4404 if exc.code == ErrorCode.NOT_FOUND else 1011)
        except Exception as exc:
            logger.error("WS v2 读取失败 type=%s", type(exc).__name__)
            await self.ws.close(code=1011)

    async def receive(self) -> None:
        """仅等待短事务接受结果；模型/工具由服务启动的 Runtime 后台任务执行。"""
        while True:
            command = None
            try:
                command = parse_command(await self.ws.receive_text())
                if command.type == "subscribe":
                    await self.subscribe(command)
                    continue
                if command.session_id != self.session_id:
                    raise AppError(ErrorCode.NOT_FOUND, "未订阅会话")
                access = await self.service.authorize(self.actor_id, command.session_id)
                if command.type == "ping":
                    self.control("pong", command.data)
                elif command.type == "unsubscribe":
                    await self.stop_subscription()
                    self.control("command.accepted", {}, command.request_id)
                elif command.type == "trace.subscribe":
                    if not access.trace:
                        raise AppError(ErrorCode.UNAUTHORIZED, "没有诊断权限")
                    self.trace_enabled, self.trace_history = True, True
                    self.trace_seq = command.data["after_seq"]
                    etag = event_schema_catalog_etag()
                    if command.data.get("catalog_etag") != etag:
                        self.control("schema.catalog", {
                            "etag": etag, "facts": event_schema_catalog(),
                            "stream": schema_catalog(),
                        })
                    self.control("command.accepted", {}, command.request_id)
                elif command.type == "trace.unsubscribe":
                    self.trace_enabled = False
                    self.control("command.accepted", {}, command.request_id)
                elif command.type in MUTATING_COMMANDS:
                    if not self.ready:
                        raise AppError(ErrorCode.CONCURRENCY, "等待回放或快照同步")
                    if not access.write:
                        raise AppError(ErrorCode.UNAUTHORIZED, "没有写权限")
                    receipt = await self.service.execute_command(
                        self.actor_id, self.connection_id, command,
                    )
                    self.enqueue(frame(
                        "command.accepted", receipt.data, session_id=self.session_id,
                        request_id=command.request_id, correlation=receipt.correlation,
                    ))
            except AppError as exc:
                if exc.code == ErrorCode.NOT_FOUND:
                    await self.ws.close(code=4404)
                    return
                self.reject(exc.code, command)
            except WebSocketDisconnect:
                return
            except Exception as exc:
                logger.error("WS v2 命令失败 type=%s", type(exc).__name__)
                self.reject(ErrorCode.INTERNAL, command)

    async def run(self) -> None:
        """管理连接任务并在所有退出路径释放控制权，不 await 整轮结算。"""
        self.control("hello", {"protocol_version": 2})
        self.control("capabilities", {
            "commands": sorted(_DATA_TYPES), "stream_schema_version": "agent-loop-stream.v2.1",
        })
        tasks = [
            asyncio.create_task(self.sender()), asyncio.create_task(self.receive()),
            asyncio.create_task(self.slow.wait()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if self.slow.is_set():
                await self.ws.close(code=4408, reason="连接过慢，请按游标重新订阅")
        except (TimeoutError, WebSocketDisconnect):
            with suppress(RuntimeError, WebSocketDisconnect):
                await self.ws.close(code=4408, reason="连接发送超时")
        except AppError as exc:
            await self.ws.close(code=4404 if exc.code == ErrorCode.NOT_FOUND else 1011)
        except Exception as exc:
            logger.error("WS v2 连接失败 type=%s", type(exc).__name__)
            with suppress(RuntimeError, WebSocketDisconnect):
                await self.ws.close(code=1011)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.stop_subscription()


@router.websocket("/ws/agent/v2")
async def agent_websocket_v2(websocket: WebSocket) -> None:
    """消费短票后建立新协议连接；缺少主服务时明确不可用。"""
    service = getattr(websocket.app.state, "loop_service", None)
    if service is None:
        await websocket.close(code=1013, reason="Agent Loop 服务未启用")
        return
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4401, reason="WebSocket 短票无效")
        return
    try:
        actor_id = await service.authenticate(ticket)
        if not isinstance(actor_id, str) or not actor_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "用户不可用")
    except Exception as exc:
        logger.info("WS v2 鉴权失败 type=%s", type(exc).__name__)
        await websocket.close(code=4401, reason="WebSocket 短票无效")
        return
    await websocket.accept()
    await WsV2Connection(websocket, service, actor_id).run()
