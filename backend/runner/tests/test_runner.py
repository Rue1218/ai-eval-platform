"""独立沙箱 Runner 服务单测（P4-2；F2/G4 契约）。

覆盖：/health、/run 正常往返（policy{mode, workspace_root}）、空命令/
非法 mode/缺失 policy/工作区越界与符号链接逃逸 → VALIDATION、嵌套 scope
接受、read-only 档位透传、SandboxError 错误码映射、/probe、未预期异常兜底
INTERNAL。真实 bwrap 行为由 ``test_harness_sandbox.py``（shared 内核）在
特权容器内覆盖；路径校验以 pytest tmp_path 真实目录驱动（跨平台）。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest
import runner.main as main
from shared.sandbox_kernel import SandboxError


class _Server:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), main._SandboxHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        """停服后等待线程退出，避免 Windows 下相邻用例复用端口时偶发断连。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def server() -> _Server:
    instance = _Server()
    yield instance
    instance.close()


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """真实工作区根：monkeypatch WORKSPACE_ROOT 指向 tmp 目录并建一个工作区。"""
    root = tmp_path / "workspaces"
    root.mkdir()
    (root / "ws-1").mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", str(root))
    return root


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _run_payload(ws, *, workspace_root: str | None = None, **overrides: object) -> dict:
    """F2/G4 契约：{command, policy{mode, workspace_root}, timeout_s, limits}。"""
    payload: dict = {
        "command": "echo hi",
        "policy": {
            "mode": "workspace-write",
            "workspace_root": workspace_root or str(ws / "ws-1"),
        },
        "timeout_s": 5.0,
        "limits": {"memory_kb": 262144, "nproc": 32, "cpu_s": 10},
    }
    payload.update(overrides)
    return payload


def test_health(server: _Server) -> None:
    with urlopen(server.url("/health"), timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
    # D4/G3：health 暴露执行槽位负载（max_workers/running/queued）
    assert body["status"] == "ok"
    assert isinstance(body.get("max_workers"), int)
    assert "running" in body and "queued" in body


def test_concurrent_runs_never_exceed_max_workers(server: _Server, ws, monkeypatch) -> None:
    """并发上限（D4/G3）：8 并发慢命令在 4 槽位下排队执行，实测并发 ≤4 且全部成功。"""
    import threading
    import time

    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def slow_run(_cmd: str, **kwargs: object) -> str:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.25)
        with lock:
            state["active"] -= 1
        return "ok"

    monkeypatch.setattr(main, "run_sandboxed", slow_run)
    results: list[tuple[int, dict]] = [None] * 8  # type: ignore[list-item]

    def worker(index: int) -> None:
        results[index] = _post(server.url("/run"), _run_payload(ws))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert state["peak"] <= main.MAX_WORKERS
    assert all(status == 200 and body.get("ok") is True for status, body in results)


def test_busy_when_slots_exhausted(server: _Server, ws, monkeypatch) -> None:
    """等待超时仍无槽位 → 200 + BUSY 错误码（api 映射 CONCURRENCY，D4/G3）。"""
    gate = main._SlotGate(1)
    monkeypatch.setattr(main, "SLOT_GATE", gate)
    monkeypatch.setattr(main, "SLOT_WAIT_S", 0.05)
    assert gate.acquire(timeout_s=0) is True
    try:
        status, body = _post(server.url("/run"), _run_payload(ws))
        assert status == 200
        assert body["ok"] is False
        assert body["error"]["code"] == "BUSY"
    finally:
        gate.release()


def test_run_ok_passes_kernel_and_returns_output(server: _Server, ws, monkeypatch) -> None:
    captured: dict = {}

    def fake_run(cmd: str, **kwargs: object) -> str:
        captured["cmd"] = cmd
        captured["sandbox_dir"] = kwargs["sandbox_dir"]
        captured["mode"] = kwargs["mode"]
        captured["timeout_s"] = kwargs["timeout_s"]
        captured["limits"] = kwargs["limits"]
        captured["bwrap_bin"] = kwargs["bwrap_bin"]
        return "hi\n"

    monkeypatch.setattr(main, "run_sandboxed", fake_run)
    status, body = _post(server.url("/run"), _run_payload(ws))
    assert status == 200
    assert body == {"ok": True, "output": "hi\n"}
    assert captured["cmd"] == "echo hi"
    # runner 校验后 bind 使用 canonical 路径（resolve realpath 结果）
    assert captured["sandbox_dir"] == os.path.realpath(str(ws / "ws-1"))
    assert captured["mode"] == "workspace-write"
    assert captured["timeout_s"] == 5.0
    assert captured["limits"].memory_kb == 262144
    assert captured["bwrap_bin"] == "/usr/bin/bwrap"


def test_run_nested_scope_accepted(server: _Server, ws, monkeypatch) -> None:
    """MAJ-5：嵌套 scope（{root}/<ws>/<folder>）通过前缀校验（旧直接子目录语义放开）。"""
    nested = ws / "ws-1" / "sub"
    nested.mkdir()
    captured: dict = {}

    def fake_run(_cmd: str, **kwargs: object) -> str:
        captured["sandbox_dir"] = kwargs["sandbox_dir"]
        return "ok"

    monkeypatch.setattr(main, "run_sandboxed", fake_run)
    status, body = _post(server.url("/run"), _run_payload(ws, workspace_root=str(nested)))
    assert status == 200
    assert body == {"ok": True, "output": "ok"}
    assert captured["sandbox_dir"] == os.path.realpath(str(nested))


def test_run_read_only_mode_forwarded(server: _Server, ws, monkeypatch) -> None:
    """read-only 档位通过校验并透传 kernel（bind mode 化）。"""
    captured: dict = {}

    def fake_run(_cmd: str, **kwargs: object) -> str:
        captured["mode"] = kwargs["mode"]
        return "ok"

    monkeypatch.setattr(main, "run_sandboxed", fake_run)
    payload = _run_payload(ws)
    payload["policy"] = {"mode": "read-only", "workspace_root": str(ws / "ws-1")}
    status, body = _post(server.url("/run"), payload)
    assert status == 200
    assert body["ok"] is True
    assert captured["mode"] == "read-only"


def test_run_stream_forwards_chunks_then_result(server: _Server, ws, monkeypatch) -> None:
    """流式端点按 NDJSON 逐块发送 stdout，终态帧不重复正文。"""

    def fake_run(_cmd: str, **kwargs: object) -> str:
        callback = kwargs["on_output"]
        assert callable(callback)
        callback("第一行\n")
        callback("第二行\n")
        return "第一行\n第二行\n"

    monkeypatch.setattr(main, "run_sandboxed", fake_run)
    req = Request(
        server.url("/run/stream"),
        data=json.dumps(_run_payload(ws)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as response:
        frames = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
    assert frames == [
        {"type": "output", "chunk": "第一行\n"},
        {"type": "output", "chunk": "第二行\n"},
        {"type": "result", "ok": True},
    ]


def test_run_empty_command_rejected(server: _Server, ws) -> None:
    status, body = _post(server.url("/run"), _run_payload(ws, command="   "))
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"


def test_run_blocklist_removed_sudo_executes(server: _Server, ws, monkeypatch) -> None:
    """F2/G4：词表删除——sudo 不再被 runner 硬拒，直通 kernel 按档位执行。"""
    captured: dict = {}

    def fake_run(cmd: str, **kwargs: object) -> str:
        captured["cmd"] = cmd
        return "uid=0(root)"

    monkeypatch.setattr(main, "run_sandboxed", fake_run)
    status, body = _post(server.url("/run"), _run_payload(ws, command="sudo id -u"))
    assert status == 200
    assert body == {"ok": True, "output": "uid=0(root)"}
    assert captured["cmd"] == "sudo id -u"


def test_run_policy_missing_rejected(server: _Server, ws) -> None:
    """双向兼容 fail-closed：policy 缺失（旧 api 载荷）→ VALIDATION，不猜测档位。"""
    payload = _run_payload(ws)
    del payload["policy"]
    status, body = _post(server.url("/run"), payload)
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"
    assert "mode" in body["error"]["message"]


def test_run_invalid_mode_rejected(server: _Server, ws) -> None:
    status, body = _post(server.url("/run"), _run_payload(ws, policy={"mode": "mutating", "workspace_root": str(ws / "ws-1")}))
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"
    assert "mode" in body["error"]["message"]


def test_run_workspace_outside_root_rejected(server: _Server, ws) -> None:
    """越出工作区根（含 .. 段归一至根自身）一律拒绝。"""
    bad_roots = (
        str(ws / ".." / "elsewhere"),  # 根外
        str(ws / "ws-1" / ".."),  # 归一后 == 根自身
        str(ws.parent / "outside"),
    )
    for bad in bad_roots:
        status, body = _post(server.url("/run"), _run_payload(ws, workspace_root=bad))
        assert status == 200
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION"
        assert "工作区" in body["error"]["message"] or "根目录" in body["error"]["message"]


def test_run_symlink_escape_rejected(server: _Server, ws, monkeypatch) -> None:
    """符号链接段指向根外 → realpath 逐段重验拒绝（MAJ-5）。"""
    secret = ws.parent / "secret-dir"
    secret.mkdir()
    link = ws / "ws-1" / "escape"
    try:
        os.symlink(str(secret), str(link), target_is_directory=True)
    except OSError:
        pytest.skip("当前环境无符号链接权限")
    status, body = _post(server.url("/run"), _run_payload(ws, workspace_root=str(link)))
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"
    assert "符号链接" in body["error"]["message"]


def test_run_sandbox_error_maps_to_json(server: _Server, ws, monkeypatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise SandboxError("TIMEOUT", "命令执行超时")

    monkeypatch.setattr(main, "run_sandboxed", boom)
    status, body = _post(server.url("/run"), _run_payload(ws))
    assert status == 200
    assert body == {"ok": False, "error": {"code": "TIMEOUT", "message": "命令执行超时"}}


def test_run_unexpected_exception_normalized_internal(server: _Server, ws, monkeypatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("secret traceback")

    monkeypatch.setattr(main, "run_sandboxed", boom)
    status, body = _post(server.url("/run"), _run_payload(ws))
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "INTERNAL"
    assert "traceback" not in body["error"]["message"]


def test_probe(server: _Server, monkeypatch) -> None:
    monkeypatch.setattr(main, "probe_sandbox", lambda **_kwargs: True)
    status, body = _post(server.url("/probe"), {})
    assert status == 200
    assert body == {"ok": True}


def test_unknown_endpoint_404(server: _Server) -> None:
    from urllib.error import HTTPError

    req = Request(
        server.url("/nope"),
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=5):
            raise AssertionError("expected HTTPError")
    except HTTPError as exc:
        assert exc.code == 404
        body = json.loads(exc.read().decode("utf-8"))
        assert body["ok"] is False
