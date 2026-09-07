"""独立沙箱 Runner 服务（P4-2）。

bash MCP Server 的执行体从 api 容器迁出：本服务在特权容器内运行 bwrap，
api 经 HTTP JSON 调用，不再持有 ``privileged``/``seccomp:unconfined``/
``SYS_ADMIN`` 与 bubblewrap，缩小攻击面。

端点（仅 compose 内网可达，不发布主机端口）：

- ``POST /run``：body ``{command, sandbox_dir, timeout_s, limits,
  max_output_chars}`` → ``{ok:true, output}`` 或 ``{ok:false,
  error:{code,message}}``。命令黑名单 + 工作区路径强校验（纵深防御，api
  侧有同等校验）；fail-closed：bwrap 缺失/启动失败一律返回 VALIDATION。
- ``POST /run/stream``：NDJSON 输出块 + 最终结果，仅供 API 内网转发 ToolCard。
- ``POST /probe``：bwrap 冒烟探测 → ``{ok:bool}``。
- ``GET /health``：``{"status":"ok"}``。

日志脱敏：不打印命令原文/参数（红色红线 X-A4）。
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from shared.sandbox_kernel import (
    SandboxError,
    SandboxLimits,
    check_bash_blocklist,
    is_valid_session_workspace,
    probe_sandbox,
    run_sandboxed,
)

RUNNER_HOST = os.environ.get("RUNNER_HOST", "0.0.0.0")
RUNNER_PORT = int(os.environ.get("RUNNER_PORT", "8001"))
# 工作区根（api 与 runner 都挂载同一 ./data:/data，路径两侧一致）
WORKSPACE_ROOT = os.environ.get("SANDBOX_WORKSPACE_ROOT", "/data/workspaces")
BWRAP_BIN = os.environ.get("SANDBOX_BWRAP_BIN", "/usr/bin/bwrap")
# 墙钟超时上限（防御畸形请求拖住 worker 线程）
MAX_TIMEOUT_S = 60.0
MAX_OUTPUT_CHARS = 20000
# 并发配额（D4/G3）：固定 worker 槽位 + 限时等待队列；超时返回 429 BUSY
MAX_WORKERS = int(os.environ.get("RUNNER_MAX_WORKERS", "4"))
SLOT_WAIT_S = float(os.environ.get("RUNNER_SLOT_WAIT_S", "5.0"))


class _SlotGate:
    """全局执行槽位（bounded semaphore）+ 可观测计数（running/queued）。

    ``health`` 暴露负载；请求超时等待后仍无槽位 → 429 + 错误码 BUSY
    （api 映射 CONCURRENCY 文案），不无限排队（D4）。
    """

    def __init__(self, max_workers: int) -> None:
        self._max = max_workers
        self._sem = threading.BoundedSemaphore(max_workers)
        self._lock = threading.Lock()
        self._running = 0
        self._queued = 0

    def acquire(self, timeout_s: float) -> bool:
        with self._lock:
            self._queued += 1
        try:
            ok = self._sem.acquire(timeout=timeout_s)
        finally:
            with self._lock:
                self._queued -= 1
        if ok:
            with self._lock:
                self._running += 1
        return ok

    def release(self) -> None:
        with self._lock:
            self._running -= 1
        self._sem.release()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "max_workers": self._max,
                "running": self._running,
                "queued": self._queued,
            }


SLOT_GATE = _SlotGate(MAX_WORKERS)


class _SandboxHandler(BaseHTTPRequestHandler):
    """JSON 端点；日志静默（命令/参数不入日志）。"""

    # ruff: noqa: N802  （BaseHTTPRequestHandler 方法名约定）

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise SandboxError("VALIDATION", "请求体不是有效 JSON") from None
        if not isinstance(payload, dict):
            raise SandboxError("VALIDATION", "请求体必须是 JSON 对象")
        return payload

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ANN001
        """静默访问日志：不记录命令与参数。"""

    def _acquire_slot(self) -> bool:
        """占执行槽位（限时等待）；失败时请求方须回 429 BUSY。"""
        return SLOT_GATE.acquire(timeout_s=SLOT_WAIT_S)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            payload = {"status": "ok"}
            payload.update(SLOT_GATE.snapshot())
            self._send(200, payload)
        else:
            self._send(404, {"ok": False, "error": {"code": "VALIDATION", "message": "未知端点"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path in {"/run", "/run/stream", "/probe"}:
            if not self._acquire_slot():
                self._send(200, {"ok": False, "error": {"code": "BUSY", "message": "沙箱执行槽位繁忙，请稍后重试"}})
                return
            try:
                if self.path == "/run":
                    self._handle_run()
                elif self.path == "/run/stream":
                    self._handle_run_stream()
                else:
                    self._send(200, {"ok": probe_sandbox(bwrap_bin=BWRAP_BIN)})
            finally:
                SLOT_GATE.release()
        else:
            self._send(404, {"ok": False, "error": {"code": "VALIDATION", "message": "未知端点"}})

    def _run_from_payload(self, *, on_output: Callable[[str], None] | None = None) -> str:
        """校验请求后执行 bwrap；流式和非流式端点共用同一安全边界。"""
        payload = self._read_body()
        command = str(payload.get("command") or "")
        sandbox_dir = str(payload.get("sandbox_dir") or "")
        # 命令与路径校验（纵深防御，独立于 api 侧）
        if not command.strip():
            raise SandboxError("VALIDATION", "bash 命令为空")
        blocked = check_bash_blocklist(command)
        if blocked is not None:
            raise SandboxError("VALIDATION", "bash 命令命中黑名单")
        if not is_valid_session_workspace(sandbox_dir, WORKSPACE_ROOT):
            raise SandboxError("VALIDATION", "非法工作区路径")
        try:
            timeout_s = float(payload.get("timeout_s", 15.0))
        except (TypeError, ValueError):
            raise SandboxError("VALIDATION", "timeout_s 非法") from None
        if not 0 < timeout_s <= MAX_TIMEOUT_S:
            raise SandboxError("VALIDATION", "timeout_s 超出允许范围")
        limits_dict = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
        try:
            limits = SandboxLimits(**limits_dict)  # type: ignore[arg-type]
        except TypeError:
            raise SandboxError("VALIDATION", "limits 字段非法") from None
        max_output = int(payload.get("max_output_chars", MAX_OUTPUT_CHARS))
        if max_output <= 0 or max_output > 1_000_000:
            max_output = MAX_OUTPUT_CHARS
        return run_sandboxed(
            command,
            sandbox_dir=sandbox_dir,
            timeout_s=timeout_s,
            limits=limits,
            bwrap_bin=BWRAP_BIN,
            max_output_chars=max_output,
            on_output=on_output,
        )

    def _send_stream(self, body: dict[str, Any]) -> None:
        """发送一条 NDJSON 瞬态帧；该端点仅暴露在 Compose 内网。"""
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") + b"\n"
        self.wfile.write(payload)
        self.wfile.flush()

    def _handle_run(self) -> None:
        try:
            output = self._run_from_payload()
        except SandboxError as exc:
            self._send(200, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        except Exception:  # noqa: BLE001 —— 兜底：任何未预期错误归一为 INTERNAL，不泄露 traceback
            self._send(200, {"ok": False, "error": {"code": "INTERNAL", "message": "沙箱执行失败"}})
            return
        self._send(200, {"ok": True, "output": output})

    def _handle_run_stream(self) -> None:
        """执行 bash 并逐行输出 NDJSON；最终帧不重复回传完整正文。"""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self._run_from_payload(
                on_output=lambda chunk: self._send_stream({"type": "output", "chunk": chunk})
            )
        except SandboxError as exc:
            self._send_stream(
                {"type": "result", "ok": False, "error": {"code": exc.code, "message": exc.message}}
            )
            return
        except Exception:  # noqa: BLE001 —— 流式端点同样禁止泄露内部异常
            self._send_stream(
                {"type": "result", "ok": False, "error": {"code": "INTERNAL", "message": "沙箱执行失败"}}
            )
            return
        self._send_stream({"type": "result", "ok": True})

def serve(host: str = RUNNER_HOST, port: int = RUNNER_PORT) -> None:
    """启动沙箱 runner HTTP 服务（前台阻塞）。"""
    server = ThreadingHTTPServer((host, port), _SandboxHandler)
    server.daemon_threads = True
    print(f"sandbox runner listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    serve()
