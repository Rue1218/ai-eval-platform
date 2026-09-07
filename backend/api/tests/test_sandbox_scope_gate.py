"""api 沙箱每 scope 并发闸门单测（D4/G3，设计文档 B 稿 S2/D4）。

覆盖：闸门按工作区目录注册并共享；闸门占用时 run_sandboxed 限时等待超时
返回 CONCURRENCY（不发起 HTTP）；并发线程同 scope 串行（实测同时持有 ≤1）。
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from app.errors import AppError, ErrorCode
from app.harness.execution import sandbox as sandbox_mod

_DIR = "/data/workspaces/834a68f1-a4fd-4261-8677-6f51830c895d"


class _FakeResp:
    """伪造 urlopen 响应（with 语义需要真类方法绑定）。"""

    def __init__(self, body: dict) -> None:
        self._raw = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._raw


class TestScopeGateRegistry:
    def test_same_scope_shares_gate(self) -> None:
        assert sandbox_mod._scope_gate(_DIR) is sandbox_mod._scope_gate(_DIR)

    def test_different_scopes_have_distinct_gates(self) -> None:
        other = "/data/workspaces/ef459f86-112c-4b13-9b0f-cab7f26f7a05"
        assert sandbox_mod._scope_gate(_DIR) is not sandbox_mod._scope_gate(other)


class TestScopeGateSerial:
    def test_concurrent_holders_never_exceed_one(self) -> None:
        gate = sandbox_mod._scope_gate(_DIR)
        lock = threading.Lock()
        state = {"holders": 0, "peak": 0}

        def worker() -> None:
            acquired = gate.acquire(timeout=10)
            try:
                if acquired:
                    with lock:
                        state["holders"] += 1
                        state["peak"] = max(state["peak"], state["holders"])
                    time.sleep(0.2)
                    with lock:
                        state["holders"] -= 1
            finally:
                if acquired:
                    gate.release()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert state["peak"] == 1

    def test_run_sandboxed_busy_when_gate_held(self, monkeypatch) -> None:
        """同 scope 闸门被占用且等待超时 → CONCURRENCY（不触碰 HTTP）。"""
        called: list[bool] = []
        monkeypatch.setattr(
            sandbox_mod,
            "settings",
            SimpleNamespace(sandbox_bash_gate_timeout_s=0.05, sandbox_runner_url="http://runner:8001"),
        )

        def fake_urlopen(*_args: object, **_kwargs: object):
            called.append(True)
            raise AssertionError("闸门未生效，不应发起 HTTP")

        monkeypatch.setattr(sandbox_mod, "urlopen", fake_urlopen)
        gate = sandbox_mod._scope_gate(_DIR)
        assert gate.acquire(timeout=0) is True
        try:
            with pytest.raises(AppError) as exc_info:
                sandbox_mod.run_sandboxed("echo hi", sandbox_dir=_DIR, timeout_s=5.0)
            assert exc_info.value.code == ErrorCode.CONCURRENCY
            assert called == []
        finally:
            gate.release()

    def test_gate_released_on_success(self, monkeypatch) -> None:
        """成功路径（含 fake HTTP）后闸门释放——下一调用立即可进。"""
        monkeypatch.setattr(
            sandbox_mod,
            "settings",
            SimpleNamespace(sandbox_bash_gate_timeout_s=30.0, sandbox_runner_url="http://runner:8001"),
        )

        def fake_urlopen(*_args: object, **_kwargs: object):
            return _FakeResp({"ok": True, "output": "hi"})

        monkeypatch.setattr(sandbox_mod, "urlopen", fake_urlopen)
        gate = sandbox_mod._scope_gate(_DIR)
        result = sandbox_mod.run_sandboxed("echo hi", sandbox_dir=_DIR, timeout_s=5.0)
        assert result == "hi"
        # 成功后闸门已释放：立即再次持有成功
        assert gate.acquire(timeout=0) is True
        gate.release()
