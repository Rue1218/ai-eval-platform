"""api 沙箱远程客户端单测（P4-2）。

覆盖：/run payload 构造、ok 映射、TIMEOUT/VALIDATION/INTERNAL 错误码映射、
网络失败 fail-closed、空命令前置拒绝、/probe 成功/失败。全部 monkeypatch
``urllib.request.urlopen``，不发起真实 HTTP。
"""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest
from shared.sandbox_kernel import SandboxLimits

from app.errors import AppError, ErrorCode
from app.harness.execution import sandbox as sandbox_mod

_UUID = "c09bd564-1443-4a2e-b085-70e719818d08"


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _patch_urlopen(monkeypatch, body: dict | Exception, *, capture: dict | None = None):
    def fake_urlopen(request, timeout: float = 0.0):  # noqa: ANN001
        if capture is not None:
            capture["request"] = request
            capture["timeout"] = timeout
        if isinstance(body, Exception):
            raise body
        return _FakeResponse(body)

    monkeypatch.setattr(sandbox_mod, "urlopen", fake_urlopen)


def test_run_ok_sends_payload_and_returns_output(monkeypatch) -> None:
    capture: dict = {}
    _patch_urlopen(
        monkeypatch,
        {"ok": True, "output": "hello"},
        capture=capture,
    )
    result = sandbox_mod.run_sandboxed(
        "echo hello",
        sandbox_dir=f"/data/workspaces/{_UUID}",
        timeout_s=5.0,
        limits=SandboxLimits(memory_kb=262144, nproc=32, cpu_s=10),
    )
    assert result == "hello"
    payload = json.loads(capture["request"].data.decode("utf-8"))
    assert payload["command"] == "echo hello"
    assert payload["sandbox_dir"] == f"/data/workspaces/{_UUID}"
    assert payload["timeout_s"] == 5.0
    assert payload["limits"] == {"memory_kb": 262144, "nproc": 32, "cpu_s": 10}
    assert payload["max_output_chars"] == 20000
    assert capture["request"].get_method() == "POST"
    assert "/run" in capture["request"].full_url
    assert capture["timeout"] >= 5.0


def test_run_empty_command_rejected_before_http(monkeypatch) -> None:
    called: dict = {"hit": False}

    def fake_urlopen(*_args: object, **_kwargs: object):  # noqa: ANN002, ANN003
        called["hit"] = True
        raise AssertionError("不应发起 HTTP")

    monkeypatch.setattr(sandbox_mod, "urlopen", fake_urlopen)
    with pytest.raises(AppError) as error:
        sandbox_mod.run_sandboxed("   ", sandbox_dir="/tmp", timeout_s=5.0)
    assert error.value.code == ErrorCode.VALIDATION
    assert called["hit"] is False


@pytest.mark.parametrize(
    ("runner_code", "expected_code"),
    [("TIMEOUT", ErrorCode.TIMEOUT), ("VALIDATION", ErrorCode.VALIDATION), ("INTERNAL", ErrorCode.INTERNAL)],
)
def test_run_maps_runner_error_codes(monkeypatch, runner_code: str, expected_code: ErrorCode) -> None:
    _patch_urlopen(
        monkeypatch,
        {"ok": False, "error": {"code": runner_code, "message": f"{runner_code} 消息"}},
    )
    with pytest.raises(AppError) as error:
        sandbox_mod.run_sandboxed("echo hi", sandbox_dir="/tmp", timeout_s=5.0)
    assert error.value.code == expected_code
    assert f"{runner_code} 消息" in error.value.message


def test_run_network_failure_fail_closed(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, URLError("runner down"))
    with pytest.raises(AppError) as error:
        sandbox_mod.run_sandboxed("echo hi", sandbox_dir="/tmp", timeout_s=5.0)
    assert error.value.code == ErrorCode.VALIDATION
    assert "沙箱引擎不可用" in error.value.message


def test_run_bad_json_fail_closed(monkeypatch) -> None:
    class _BadResponse:
        def __enter__(self) -> _BadResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return b"not json{"

    monkeypatch.setattr(sandbox_mod, "urlopen", lambda *a, **k: _BadResponse())
    with pytest.raises(AppError) as error:
        sandbox_mod.run_sandboxed("echo hi", sandbox_dir="/tmp", timeout_s=5.0)
    assert error.value.code == ErrorCode.VALIDATION
    assert "沙箱引擎不可用" in error.value.message


def test_probe_ok(monkeypatch) -> None:
    sandbox_mod.reset_probe_cache()
    _patch_urlopen(monkeypatch, {"ok": True})
    assert sandbox_mod.probe_sandbox() is True


def test_probe_fail_closed(monkeypatch) -> None:
    sandbox_mod.reset_probe_cache()
    _patch_urlopen(monkeypatch, URLError("down"))
    assert sandbox_mod.probe_sandbox() is False
