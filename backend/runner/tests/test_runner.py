"""独立沙箱 Runner 服务单测（P4-2）。

覆盖：/health、/run 正常往返、命令为空/黑名单/非法工作区路径 → VALIDATION、
SandboxError 错误码映射、/probe、未预期异常兜底 INTERNAL。真实 bwrap 行为由
``test_harness_sandbox.py``（shared 内核）在特权容器内覆盖。
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest
import runner.main as main
from shared.sandbox_kernel import SandboxError

_UUID = "c09bd564-1443-4a2e-b085-70e719818d08"


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


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _run_payload(**overrides: object) -> dict:
    payload: dict = {
        "command": "echo hi",
        "sandbox_dir": f"/data/workspaces/{_UUID}",
        "timeout_s": 5.0,
        "limits": {"memory_kb": 262144, "nproc": 32, "cpu_s": 10},
    }
    payload.update(overrides)
    return payload


def test_health(server: _Server) -> None:
    with urlopen(server.url("/health"), timeout=5) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8")) == {"status": "ok"}


def test_run_ok_passes_kernel_and_returns_output(server: _Server, monkeypatch) -> None:
    captured: dict = {}

    def fake_run(cmd: str, **kwargs: object) -> str:
        captured["cmd"] = cmd
        captured["sandbox_dir"] = kwargs["sandbox_dir"]
        captured["timeout_s"] = kwargs["timeout_s"]
        captured["limits"] = kwargs["limits"]
        captured["bwrap_bin"] = kwargs["bwrap_bin"]
        return "hi\n"

    monkeypatch.setattr(main, "run_sandboxed", fake_run)
    status, body = _post(server.url("/run"), _run_payload())
    assert status == 200
    assert body == {"ok": True, "output": "hi\n"}
    assert captured["cmd"] == "echo hi"
    assert captured["sandbox_dir"] == f"/data/workspaces/{_UUID}"
    assert captured["timeout_s"] == 5.0
    assert captured["limits"].memory_kb == 262144
    assert captured["bwrap_bin"] == "/usr/bin/bwrap"


def test_run_stream_forwards_chunks_then_result(server: _Server, monkeypatch) -> None:
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
        data=json.dumps(_run_payload()).encode("utf-8"),
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


def test_run_empty_command_rejected(server: _Server) -> None:
    status, body = _post(server.url("/run"), _run_payload(command="   "))
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"


def test_run_blocklisted_command_rejected(server: _Server) -> None:
    # sudo 属「不可确认后执行」类（提权），runner 必须独立硬拒；
    # rm/chmod 等改动工作区的命令走 HITL 确认，批准后应放行（不再在此断言）。
    status, body = _post(server.url("/run"), _run_payload(command="sudo id -u"))
    assert status == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"
    assert "黑名单" in body["error"]["message"]


def test_run_invalid_workspace_rejected(server: _Server) -> None:
    for bad_dir in ("/etc", f"/data/workspaces/{_UUID}/sub", "/data/workspaces/.."):
        status, body = _post(server.url("/run"), _run_payload(sandbox_dir=bad_dir))
        assert status == 200
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION"
        assert "工作区" in body["error"]["message"]


def test_run_sandbox_error_maps_to_json(server: _Server, monkeypatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise SandboxError("TIMEOUT", "命令执行超时")

    monkeypatch.setattr(main, "run_sandboxed", boom)
    status, body = _post(server.url("/run"), _run_payload())
    assert status == 200
    assert body == {"ok": False, "error": {"code": "TIMEOUT", "message": "命令执行超时"}}


def test_run_unexpected_exception_normalized_internal(server: _Server, monkeypatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("secret traceback")

    monkeypatch.setattr(main, "run_sandboxed", boom)
    status, body = _post(server.url("/run"), _run_payload())
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
