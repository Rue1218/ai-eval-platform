"""执行接口真实 HTTP 契约测试；内核替身只模拟证据，不冒充 Linux 整树验证。"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
import runner.main as main
from shared.sandbox_kernel import SandboxError


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    """每例独立注册表、槽位、令牌和真实工作区。"""
    monkeypatch.setattr(main, "EXECUTIONS", main._ExecutionRegistry())
    monkeypatch.setattr(main, "SLOT_GATE", main._SlotGate(2))
    monkeypatch.setattr(main, "INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(main, "WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "workspace").mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), main._SandboxHandler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()

    def send(method, path, payload=None, *, token="test-internal-token", instance=None):
        """保留 HTTP 错误响应，便于断言鉴权及实例围栏。"""
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "X-Runner-Instance-ID": instance or main.EXECUTIONS.instance_id}
        req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers=headers, method=method)
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    payload = {"execution_id": str(uuid4()), "session_id": "s", "turn_id": "t", "call_id": "c",
               "command": "echo hi", "policy": {"mode": "workspace-write", "workspace_root": str(tmp_path / "workspace")}}
    yield send, payload
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def _finished(send, execution_id):
    """有界等待执行线程结算；测试失败不会无限卡住。"""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        _, body = send("GET", f"/executions/{execution_id}")
        if body["status"] != "running":
            return body
        time.sleep(0.01)
    raise AssertionError("执行未结束")


def _success(_command, *, control, **_kwargs):
    """模拟内核同时提供正常退出和整树停止证明。"""
    control.started = True
    control.exit_code = 0
    control.process_tree_terminated = True
    control.termination_evidence = "cgroup_empty"
    return "hi"


def test_concurrent_duplicate_dispatch_executes_once(endpoint, monkeypatch):
    """同 ID 并发提交只派发一次，结束后重放仍返回原收据。"""
    send, payload = endpoint
    calls = []

    def execute(command, **kwargs):
        """记录真实派发次数。"""
        calls.append(command)
        return _success(command, **kwargs)

    monkeypatch.setattr(main, "run_sandboxed", execute)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: send("POST", "/executions", payload), range(4)))
    assert all(code in {200, 202} for code, _ in results)
    body = _finished(send, payload["execution_id"])
    assert body["status"] == "succeeded" and body["exit_code"] == 0
    assert body["canonical_scope"] == payload["policy"]["workspace_root"]
    assert send("POST", "/executions", payload)[1] == body
    assert len(calls) == 1
    conflict = {**payload, "command": "echo other"}
    assert send("POST", "/executions", conflict)[0] == 409
    assert send("POST", f"/executions/{payload['execution_id']}/cancel")[1]["status"] == "succeeded"


@pytest.mark.parametrize("proven", [True, False])
def test_cancel_needs_tree_evidence_and_bypasses_slots(endpoint, monkeypatch, proven):
    """取消响应可为 running；只有已确认整树停止才能得到 cancelled。"""
    send, payload = endpoint
    started = threading.Event()

    def execute(_command, *, control, **_kwargs):
        """等待取消信号后模拟可证实/不可证实的清理。"""
        control.started = True
        started.set()
        assert control.cancel_event.wait(2)
        control.process_tree_terminated = proven
        control.termination_evidence = "cgroup_empty" if proven else None
        raise SandboxError("CANCELLED", "命令已取消")

    monkeypatch.setattr(main, "run_sandboxed", execute)
    monkeypatch.setattr(main, "SLOT_GATE", main._SlotGate(1))
    send("POST", "/executions", payload)
    assert started.wait(1)
    path = f"/executions/{payload['execution_id']}/cancel"
    assert send("POST", path)[0] == 200
    body = _finished(send, payload["execution_id"])
    assert body["status"] == ("cancelled" if proven else "outcome_unknown")
    assert body["process_tree_terminated"] is proven
    assert send("POST", path)[1] == body


def test_cancel_before_submit_leaves_tombstone(endpoint, monkeypatch):
    """取消请求先到时，晚到的执行不得启动。"""
    send, payload = endpoint
    monkeypatch.setattr(main, "run_sandboxed", lambda *a, **k: pytest.fail("不应启动"))
    body = send("POST", f"/executions/{payload['execution_id']}/cancel")[1]
    assert body["status"] == "not_started" and body["process_tree_terminated"]
    assert send("POST", "/executions", payload)[1] == body


def test_restart_fence_and_unknown_query(endpoint, monkeypatch):
    """换实例的旧请求不能创建新执行；查无记录不等于已停止。"""
    send, payload = endpoint
    old_instance = main.EXECUTIONS.instance_id
    monkeypatch.setattr(main, "EXECUTIONS", main._ExecutionRegistry())
    monkeypatch.setattr(main, "run_sandboxed", lambda *a, **k: pytest.fail("不应启动"))
    for method, path, data in [("POST", "/executions", payload), ("GET", f"/executions/{payload['execution_id']}", None),
                               ("POST", f"/executions/{payload['execution_id']}/cancel", None)]:
        code, body = send(method, path, data, instance=old_instance)
        assert code == 409 and body["status"] == "outcome_unknown"
        assert not body["process_tree_terminated"]
    assert send("GET", f"/executions/{payload['execution_id']}")[1]["status"] == "outcome_unknown"
    assert not main.EXECUTIONS.records


def test_authentication_fails_closed(endpoint, monkeypatch):
    """只有内网令牌持有者可提交、查询或取消，未配置令牌则关闭新接口。"""
    send, payload = endpoint
    for method, path, data in [("GET", "/executions", None), ("POST", "/executions", payload),
                               ("POST", f"/executions/{payload['execution_id']}/cancel", None)]:
        assert send(method, path, data, token="wrong")[0] == 401
    monkeypatch.setattr(main, "INTERNAL_TOKEN", "")
    assert send("POST", "/executions", payload)[0] == 503
    assert not main.EXECUTIONS.records


@pytest.mark.parametrize("update", [
    {"policy": {"mode": "none", "workspace_root": "/tmp"}},
    {"limits": {"cpu_s": "1; echo unsafe"}}, {"limits": {"nproc": 10000}},
    {"limits": {"memory_kb": True}}, {"limits": []},
    {"dangerouslyDisableSandbox": True}, {"timeout_s": float("nan")},
])
def test_new_execution_rejects_unsafe_fields(endpoint, monkeypatch, update):
    """拒绝限额注入、未知降级字段和非法档位，不派发内核。"""
    send, payload = endpoint
    monkeypatch.setattr(main, "run_sandboxed", lambda *a, **k: pytest.fail("不应启动"))
    assert send("POST", "/executions", {**payload, **update})[0] == 400


def test_slots_and_receipt_capacity_do_not_reexecute(endpoint, monkeypatch):
    """忙碌收据不可重跑；达到记录容量也不驱逐可重放的旧 ID。"""
    send, payload = endpoint
    monkeypatch.setattr(main, "MAX_EXECUTION_RECORDS", 1)
    monkeypatch.setattr(main, "SLOT_GATE", main._SlotGate(1))
    assert main.SLOT_GATE.acquire(0)
    try:
        assert send("POST", "/executions", payload)[1]["status"] == "not_started"
    finally:
        main.SLOT_GATE.release()
    assert send("POST", "/executions", payload)[1]["status"] == "not_started"
    assert send("POST", "/executions", {**payload, "execution_id": str(uuid4())})[0] == 503


def test_new_execution_without_cgroup_fails_before_launch(endpoint, monkeypatch):
    """没有委派时拒绝新执行，不能降级到旧 kernel 路径。"""
    send, payload = endpoint
    monkeypatch.setattr(main, "CGROUP_ROOT", None)
    send("POST", "/executions", payload)
    body = _finished(send, payload["execution_id"])
    assert body["status"] == "not_started"
    assert body["termination_evidence"] == "not_started"
    assert body["error"]["code"] == "VALIDATION"
