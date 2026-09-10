"""新异步客户端的回执、取消、超时和实例围栏测试，不连接真实 Runner。"""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from app.harness.execution.loop_runner import LoopRunnerClient, RunnerRequest


@pytest.fixture
def execution():
    """生成相互独立的执行身份和冻结的 Runner 代次。"""
    return RunnerRequest(str(uuid4()), "s", "t", "c", "echo hi", "/data/workspaces/s"), str(uuid4())


def _body(request, instance, status="succeeded", **overrides):
    """完整可信收据，反例通过单独替换字段构造。"""
    body = {"execution_id": request.execution_id, "runner_instance_id": instance,
            "status": status, "process_tree_terminated": status != "running",
            "termination_evidence": None if status == "running" else "process_exited",
            "execution_started": True, "request_fingerprint": request.fingerprint,
            "exit_code": 0, "output": "hi"}
    return httpx.Response(200, json={**body, **overrides})


@asynccontextmanager
async def _client(handler, **kwargs):
    """注入异步 HTTP transport，保留真实客户端解析与取消路径。"""
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        # 成功路径给调度留出余量，避免 Windows 时钟粒度吞掉首次状态查询。
        options = {"poll_interval_s": 0.001, "cancel_grace_s": 1.0, **kwargs}
        yield LoopRunnerClient("http://runner", "token", client=http, **options)


@pytest.mark.asyncio
async def test_payload_and_instance_are_frozen(execution):
    """请求摘要与服务端契约一致，派发、查询都携带固定代次和令牌。"""
    request, instance = execution
    calls = []

    async def handle(http_request):
        """先接收派发，再返回完成收据。"""
        calls.append(http_request)
        assert http_request.headers["Authorization"] == "Bearer token"
        assert http_request.headers["X-Runner-Instance-ID"] == instance
        return _body(request, instance, "running" if len(calls) == 1 else "succeeded")

    async with _client(handle) as client:
        result = await client.run(request, instance)
    assert result.status == "succeeded" and result.guard_releasable
    assert [call.method for call in calls] == ["POST", "GET"]
    assert request.fingerprint == result.request_fingerprint


@pytest.mark.parametrize("override", [
    {"process_tree_terminated": False}, {"termination_evidence": None},
    {"execution_id": str(uuid4())}, {"runner_instance_id": str(uuid4())},
    {"request_fingerprint": "wrong"}, {"status": "completed"}, {"exit_code": 1},
])
@pytest.mark.asyncio
async def test_invalid_receipt_cannot_release_guard(execution, override):
    """缺少终止证明或身份不匹配的回执一律未知。"""
    request, instance = execution
    async with _client(lambda _: _body(request, instance, **override)) as client:
        result = await client.submit(request, instance)
    assert result.status == "outcome_unknown" and not result.guard_releasable


@pytest.mark.asyncio
async def test_conflicting_id_does_not_cancel_original_execution(execution):
    """提交内容冲突时不能取消已存在的另一份请求。"""
    request, instance = execution
    calls = []

    def handle(http_request):
        """只允许一次提交，任何后续取消都是错误。"""
        calls.append(http_request)
        return httpx.Response(409, json={"error": {"code": "CONFLICT"}})

    async with _client(handle) as client:
        result = await client.run(request, instance)
    assert result.error_code == "CONFLICT" and not result.guard_releasable
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_submit_timeout_cancels_without_resubmit(execution):
    """提交超时不能重试 shell；尝试取消同 ID，未知时保留 guard。"""
    request, instance = execution
    calls = []

    def handle(http_request):
        """所有网络请求超时，保证客户端不会伪造取消成功。"""
        calls.append(http_request.url.path)
        raise httpx.ReadTimeout("timeout")

    async with _client(handle) as client:
        result = await client.run(request, instance)
    assert calls == ["/executions", f"/executions/{request.execution_id}/cancel"]
    assert result.status == "outcome_unknown" and not result.guard_releasable


@pytest.mark.asyncio
async def test_cancel_before_submit_sends_only_tombstone(execution):
    """启动前已取消时只封存 ID，绝不提交执行。"""
    request, instance = execution
    cancel = asyncio.Event()
    cancel.set()

    def handle(http_request):
        """模拟服务端未启动墓碑。"""
        assert http_request.url.path.endswith("/cancel")
        return _body(request, instance, "not_started", termination_evidence="not_started",
                     execution_started=False, request_fingerprint=None)

    async with _client(handle) as client:
        result = await client.run(request, instance, cancel_event=cancel)
    assert result.status == "not_started" and result.guard_releasable


@pytest.mark.parametrize("cooperative", [True, False])
@pytest.mark.asyncio
async def test_running_cancel_waits_for_actual_result(execution, cooperative):
    """协作信号与 Task.cancel 都必须等待已证实的远端终态。"""
    request, instance = execution
    started = asyncio.Event()
    signal = asyncio.Event()
    cancelled = []

    async def handle(http_request):
        """取消先返回 running，后续查询才提供进程树停止证明。"""
        if http_request.url.path.endswith("/cancel"):
            cancelled.append(True)
            return _body(request, instance, "running")
        if cancelled:
            return _body(request, instance, "cancelled", exit_code=-9)
        started.set()
        return _body(request, instance, "running")

    async with _client(handle) as client:
        task = asyncio.create_task(client.run(request, instance, cancel_event=signal))
        await started.wait()
        if cooperative:
            signal.set()
        else:
            task.cancel()
        result = await asyncio.wait_for(task, 3)
    assert result.status == "cancelled" and result.guard_releasable
    assert len(cancelled) == 1


@pytest.mark.asyncio
async def test_cancel_grace_timeout_remains_unknown(execution):
    """取消 drain 超时后保留未知状态，不阻塞整个回合直至远端墙钟超时。"""
    request, instance = execution
    async with _client(lambda _: _body(request, instance, "running"), cancel_grace_s=0.03) as client:
        result = await client.run(request, instance, wait_timeout_s=0.01)
    assert result.status == "outcome_unknown" and not result.guard_releasable


@pytest.mark.asyncio
async def test_late_success_is_not_overwritten_by_cancel(execution):
    """网络收据丢失但执行已成功，取消查询应保留真实成功结果。"""
    request, instance = execution

    def handle(http_request):
        """提交丢包后在取消接口返回已完成结果。"""
        if http_request.url.path == "/executions":
            raise httpx.ReadTimeout("lost")
        return _body(request, instance)

    async with _client(handle) as client:
        result = await client.run(request, instance)
    assert result.status == "succeeded" and result.guard_releasable


@pytest.mark.asyncio
async def test_instance_discovery_and_connection_ownership(execution):
    """探测只返回代次；关闭包装器不关闭注入的共享连接池。"""
    _, instance = execution
    async with _client(lambda _: httpx.Response(200, json={"runner_instance_id": instance, "protocol_version": 1})) as client:
        assert await client.instance_id() == instance
        await client.aclose()
        assert not client._client.is_closed


@pytest.mark.asyncio
async def test_shutdown_cancelling_cleanup_returns_unknown(execution, monkeypatch):
    """服务关闭连清理任务一并取消时，必须返回未知，不能无限自旋。"""
    request, instance = execution

    def lost(_http_request):
        """模拟提交丢包，进入取消清理路径。"""
        raise httpx.ReadTimeout("lost")

    async def cancelled_cleanup(*_args):
        """模拟事件循环关闭时清理任务本身被取消。"""
        raise asyncio.CancelledError

    async with _client(lost) as client:
        monkeypatch.setattr(client, "_cancel_and_wait", cancelled_cleanup)
        result = await client.run(request, instance)
    assert result.status == "outcome_unknown" and not result.guard_releasable
