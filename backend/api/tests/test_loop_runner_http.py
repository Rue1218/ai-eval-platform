"""异步客户端到真实 Runner HTTP 服务的联调；Linux 内核使用明确标注的替身。"""

import asyncio
import threading
from http.server import ThreadingHTTPServer
from uuid import uuid4

import pytest
import runner.main as main
from shared.sandbox_kernel import SandboxError

from app.harness.execution.loop_runner import LoopRunnerClient, RunnerRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [True, False])
async def test_async_client_real_http_lifecycle(tmp_path, monkeypatch, cancelled):
    """验证真实 JSON 指纹、实例头、最终状态及取消信号在两端保持一致。"""
    monkeypatch.setattr(main, "EXECUTIONS", main._ExecutionRegistry())
    monkeypatch.setattr(main, "SLOT_GATE", main._SlotGate(1))
    monkeypatch.setattr(main, "INTERNAL_TOKEN", "test-token")
    monkeypatch.setattr(main, "WORKSPACE_ROOT", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = threading.Event()

    def execute(_command, *, control, **_kwargs):
        """替身只用于 HTTP 联调，不把它视为真实 cgroup 证据。"""
        control.started = True
        started.set()
        if cancelled:
            assert control.cancel_event.wait(2)
        control.process_tree_terminated = True
        control.termination_evidence = "cgroup_empty"
        control.exit_code = -9 if cancelled else 0
        if cancelled:
            raise SandboxError("CANCELLED", "命令已取消")
        return "hi"

    monkeypatch.setattr(main, "run_sandboxed", execute)
    server = ThreadingHTTPServer(("127.0.0.1", 0), main._SandboxHandler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    client = LoopRunnerClient(f"http://127.0.0.1:{server.server_port}", "test-token", poll_interval_s=0.01)
    try:
        instance = await client.instance_id()
        request = RunnerRequest(str(uuid4()), "session", "turn", "call", "echo hi", str(workspace))
        task = asyncio.create_task(client.run(request, instance))
        if cancelled:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
        result = await asyncio.wait_for(task, 2)
        assert result.status == ("cancelled" if cancelled else "succeeded")
        assert result.guard_releasable and result.request_fingerprint == request.fingerprint
        assert await client.status(request.execution_id, instance) == result
        assert await client.submit(request, instance) == result
        assert await client.cancel(request.execution_id, instance) == result
    finally:
        await client.aclose()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
