"""独立沙箱 Runner 服务（P4-2）。

bash MCP Server 的执行体从 api 容器迁出：本服务在特权容器内运行 bwrap，
api 经 HTTP JSON 调用，不再持有 ``privileged``/``seccomp:unconfined``/
``SYS_ADMIN`` 与 bubblewrap，缩小攻击面。

端点（仅 compose 内网可达，不发布主机端口）：

- ``POST /run``：body ``{command, policy{mode, workspace_root}, timeout_s,
  limits, max_output_chars}`` → ``{ok:true, output}`` 或 ``{ok:false,
  error:{code,message}}``。F2/G4：无字符串词表（§6.3）——仅工作区前缀 +
  realpath 逐段校验（接受嵌套 scope、拒符号链接逃逸）与档位校验；
  fail-closed：``policy`` 缺失/``mode`` 非法一律返回 VALIDATION（不按任何
  档位猜测），bwrap 缺失/启动失败一律返回 VALIDATION。
- ``POST /run/stream``：NDJSON 输出块 + 最终结果，仅供 API 内网转发 ToolCard。
- ``POST /probe``：bwrap 冒烟探测 → ``{ok:bool}``。
- ``GET /health``：``{"status":"ok"}``。
- ``GET /executions``：发现本次启动的实例代次。
- ``POST /executions``：按 execution_id 幂等派发，body 增加 session_id/turn_id/call_id。
- ``GET /executions/{id}``、``POST /executions/{id}/cancel``：查询与幂等取消。
  新接口均需 Bearer RUNNER_INTERNAL_TOKEN；除代次发现外还需
  X-Runner-Instance-ID。RUNNER_CGROUP_ROOT 须指向可写 cgroup v2 委派；
  无委派在启动前拒绝，缺少整树停止证据则返回 outcome_unknown。

日志脱敏：不打印命令原文/参数（红色红线 X-A4）。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

from shared.sandbox_kernel import (
    SANDBOX_MODES,
    SandboxError,
    SandboxExecutionControl,
    SandboxLimits,
    probe_sandbox,
    resolve_workspace_path,
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
# 新接口缺省关闭，令牌与 cgroup 根只由部署注入，不接受模型指定。
INTERNAL_TOKEN = os.environ.get("RUNNER_INTERNAL_TOKEN", "")
CGROUP_ROOT = os.environ.get("RUNNER_CGROUP_ROOT")
MAX_EXECUTION_RECORDS = 4096


class _SlotGate:
    """全局执行槽位（bounded semaphore）+ 可观测计数（running/queued）。

    ``health`` 暴露负载；请求超时等待后仍无槽位 → HTTP 200 + ``{ok:false,
    error:{code:"BUSY"}}``（G2G3 文档"429"口径以实现为准，api 映射
    CONCURRENCY 文案），不无限排队（D4）。
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


def _now() -> str:
    """内部回执使用 UTC 时间，便于持久 guard 对账。"""
    return datetime.now(UTC).isoformat()


@dataclass
class _Execution:
    """单实例执行收据；不淘汰 ID，防止重发导致副作用重复。"""

    execution_id: str
    request_fingerprint: str | None
    correlation: dict[str, str]
    canonical_scope: str | None = None
    status: str = "running"
    output: str = ""
    error: dict[str, str] | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None
    cancel_requested_at: str | None = None
    control: SandboxExecutionControl = field(default_factory=SandboxExecutionControl)


class _ExecutionRegistry:
    """启动代次围栏：重启后的旧实例请求只能得到 unknown，不能重新执行。"""

    def __init__(self) -> None:
        """每次进程启动生成新代次，旧请求不能跨代次重放执行。"""
        self.instance_id = str(uuid4())
        self.lock = threading.Lock()
        self.records: dict[str, _Execution] = {}

    def snapshot(self, record: _Execution) -> dict[str, Any]:
        """调用者持锁读取状态；未收到可信证据时，guard 必须维持隔离。"""
        return {
            "execution_id": record.execution_id,
            "runner_instance_id": self.instance_id,
            "request_fingerprint": record.request_fingerprint,
            "correlation": record.correlation,
            "canonical_scope": record.canonical_scope,
            "status": record.status,
            "output": record.output,
            "error": record.error,
            "created_at": record.created_at,
            "finished_at": record.finished_at,
            "cancel_requested_at": record.cancel_requested_at,
            "execution_started": record.control.started,
            "process_tree_terminated": record.control.process_tree_terminated,
            "termination_evidence": record.control.termination_evidence,
            "exit_code": record.control.exit_code,
            "cgroup_path": record.control.cgroup_path,
        }

    def unknown(self, execution_id: str) -> dict[str, Any]:
        """查无记录不是未启动证明；必须由 API 保留原执行域的 guard。"""
        return {
            "execution_id": execution_id, "runner_instance_id": self.instance_id,
            "status": "outcome_unknown", "process_tree_terminated": False,
            "termination_evidence": None,
            "error": {"code": "OUTCOME_UNKNOWN", "message": "执行记录或 Runner 实例不可证实"},
        }

    def execute(self, record: _Execution, arguments: dict[str, Any], gate: _SlotGate) -> None:
        """单独线程驱动内核，查询与取消不占执行槽；所有结果都检验终止证据。"""
        status, output, error = "succeeded", "", None
        try:
            command = arguments.pop("cmd")
            output = run_sandboxed(command, **arguments, control=record.control, cgroup_root=CGROUP_ROOT)
        except SandboxError as exc:
            status = "cancelled" if exc.code == "CANCELLED" else "denied" if exc.code == "DENIED" else "failed"
            error = {"code": exc.code, "message": exc.message}
        except Exception:  # noqa: BLE001 —— 不把内部异常原文发送给调用者
            status = "failed"
            error = {"code": "INTERNAL", "message": "沙箱执行失败"}
        finally:
            with self.lock:
                if not record.control.process_tree_terminated:
                    status = "outcome_unknown"
                    error = {"code": "OUTCOME_UNKNOWN", "message": "无法证实进程树终止，请保持工作区隔离"}
                elif not record.control.started:
                    status = "not_started"
                record.status, record.output, record.error = status, output, error
                record.finished_at = _now()
            gate.release()


EXECUTIONS = _ExecutionRegistry()


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
        if self.path == "/executions" or self.path.startswith("/executions/"):
            self._handle_execution()
        elif self.path == "/health":
            payload = {"status": "ok"}
            payload.update(SLOT_GATE.snapshot())
            self._send(200, payload)
        else:
            self._send(404, {"ok": False, "error": {"code": "VALIDATION", "message": "未知端点"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/executions" or self.path.startswith("/executions/"):
            self._handle_execution()
        elif self.path in {"/run", "/run/stream", "/probe"}:
            if not self._acquire_slot():
                self._send_busy()
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
        """校验请求后按档位执行 bwrap；流式和非流式端点共用同一安全边界。

        F2/G4 契约（§6.2）：只收 ``policy{mode, workspace_root}``——不再接收
        任何词表/黑白名单字段；policy 缺失或 mode 非法 → VALIDATION
        fail-closed（旧 api 混布时默认拒绝，不按任何档位猜测）。
        """
        arguments = self._run_arguments(self._read_body())
        return run_sandboxed(arguments.pop("cmd"), **arguments, on_output=on_output)

    @staticmethod
    def _run_arguments(payload: dict[str, Any]) -> dict[str, Any]:
        """新旧接口共用档位、scope 和资源验证，禁止新接口绕过 bwrap 边界。"""
        command = str(payload.get("command") or "")
        policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        mode = str(policy.get("mode") or "")
        workspace_root = str(policy.get("workspace_root") or "")
        if not command.strip():
            raise SandboxError("VALIDATION", "bash 命令为空")
        if mode not in SANDBOX_MODES:
            raise SandboxError("VALIDATION", "policy.mode 非法或缺失")
        # 工作区前缀 + realpath 逐段校验（MAJ-5）；返回值 = canonical 路径供
        # bind（bind realpath 最终路径，消除 resolve→bind 换链窗口）
        sandbox_dir = resolve_workspace_path(workspace_root, WORKSPACE_ROOT)
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
        return dict(cmd=command, sandbox_dir=sandbox_dir, mode=mode, timeout_s=timeout_s,
                    limits=limits, bwrap_bin=BWRAP_BIN, max_output_chars=max_output)

    def _handle_execution(self) -> None:
        """仅令牌认证的内网客户端可操作新接口；认证和实例围栏先于执行。"""
        if not INTERNAL_TOKEN:
            self._send(503, {"error": {"code": "VALIDATION", "message": "Runner 内部认证未配置"}})
            return
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {INTERNAL_TOKEN}"):
            self._send(401, {"error": {"code": "UNAUTHORIZED", "message": "Runner 内部认证失败"}})
            return
        registry = EXECUTIONS
        if self.path == "/executions" and self.command == "GET":
            self._send(200, {"runner_instance_id": registry.instance_id, "protocol_version": 1})
            return
        try:
            if self.path == "/executions" and self.command == "POST":
                payload = self._read_body()
                execution_id = str(UUID(str(payload.get("execution_id", ""))))
            else:
                parts = self.path.split("/")
                valid_get = self.command == "GET" and len(parts) == 3
                valid_cancel = self.command == "POST" and len(parts) == 4 and parts[3] == "cancel"
                if not (valid_get or valid_cancel):
                    raise SandboxError("VALIDATION", "未知执行端点")
                execution_id = str(UUID(parts[2]))
                payload = None
            if self.headers.get("X-Runner-Instance-ID") != registry.instance_id:
                self._send(409, registry.unknown(execution_id))
                return
            if payload is not None:
                status, body = self._submit_execution(registry, execution_id, payload)
            else:
                with registry.lock:
                    record = registry.records.get(execution_id)
                    if self.command == "POST":
                        if record is None and len(registry.records) < MAX_EXECUTION_RECORDS:
                            # 取消先到时落墓碑，阻止在途 POST 后到又启动命令。
                            record = _Execution(execution_id, None, {}, status="not_started", finished_at=_now())
                            record.control.process_tree_terminated = True
                            record.control.termination_evidence = "not_started"
                            registry.records[execution_id] = record
                        if record is not None and record.status in {"running", "not_started"}:
                            record.control.cancel_event.set()
                            record.cancel_requested_at = record.cancel_requested_at or _now()
                    status, body = 200, registry.snapshot(record) if record else registry.unknown(execution_id)
            self._send(status, body)
        except (SandboxError, ValueError, TypeError) as exc:
            message = exc.message if isinstance(exc, SandboxError) else "执行请求字段非法"
            self._send(400, {"error": {"code": "VALIDATION", "message": message}})

    def _submit_execution(self, registry: _ExecutionRegistry, execution_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """原子登记、幂等对比再派发；容量耗尽时不驱逐旧 ID。"""
        allowed = {"execution_id", "session_id", "turn_id", "call_id", "command", "policy", "timeout_s", "limits", "max_output_chars"}
        if payload.keys() - allowed:
            raise SandboxError("VALIDATION", "执行请求含未知字段")
        if not isinstance(payload.get("command"), str):
            raise SandboxError("VALIDATION", "command 必须是字符串")
        policy = payload.get("policy")
        if not isinstance(policy, dict) or policy.keys() != {"mode", "workspace_root"}:
            raise SandboxError("VALIDATION", "policy 字段非法")
        if not all(isinstance(value, str) for value in policy.values()):
            raise SandboxError("VALIDATION", "policy 字段类型非法")
        limits = payload.get("limits", {})
        ceilings = {"memory_kb": 262144, "nproc": 32, "cpu_s": 10}
        if not isinstance(limits, dict) or limits.keys() - ceilings.keys():
            raise SandboxError("VALIDATION", "limits 字段非法")
        for name, value in limits.items():
            if type(value) is not int or not 0 < value <= ceilings[name]:
                raise SandboxError("VALIDATION", "limits 必须为受限正整数")
        correlation = {}
        for key in ("session_id", "turn_id", "call_id"):
            value = payload.get(key)
            if not isinstance(value, str) or not value or len(value) > 200:
                raise SandboxError("VALIDATION", f"{key} 非法或缺失")
            correlation[key] = value
        arguments = self._run_arguments(payload)
        # 原始请求冻结指纹；包括身份、策略、限额，禁止同 ID 换内容。
        fingerprint = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        with registry.lock:
            record = registry.records.get(execution_id)
            if record is not None:
                if record.request_fingerprint not in (None, fingerprint):
                    return 409, {"error": {"code": "CONFLICT", "message": "execution_id 已绑定其他请求"}}
                return 200, registry.snapshot(record)
            if len(registry.records) >= MAX_EXECUTION_RECORDS:
                return 503, {"error": {"code": "BUSY", "message": "执行收据容量已满"}}
            record = _Execution(execution_id, fingerprint, correlation, canonical_scope=arguments["sandbox_dir"])
            registry.records[execution_id] = record
            gate = SLOT_GATE
            if not gate.acquire(timeout_s=0):
                record.status, record.finished_at = "not_started", _now()
                record.control.process_tree_terminated = True
                record.control.termination_evidence = "not_started"
                record.error = {"code": "BUSY", "message": "沙箱执行槽位繁忙"}
            else:
                try:
                    threading.Thread(target=registry.execute, args=(record, arguments, gate), daemon=True).start()
                except RuntimeError:
                    gate.release()
                    record.status, record.finished_at = "not_started", _now()
                    record.control.process_tree_terminated = True
                    record.control.termination_evidence = "not_started"
                    record.error = {"code": "INTERNAL", "message": "执行线程启动失败"}
            return 202, registry.snapshot(record)

    def _begin_stream(self) -> None:
        """发送 NDJSON 流式响应头（普通流与 BUSY 帧共用同一协议面）。"""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def _send_busy(self) -> None:
        """槽位耗尽响应：/run/stream 必须按 NDJSON 协议回结果帧（BLK-3 修复，
        否则 api 流式解析把 BUSY 误判为「沙箱引擎不可用」）；其余端点普通 JSON。
        """
        if self.path == "/run/stream":
            self._begin_stream()
            self._send_stream(
                {
                    "type": "result",
                    "ok": False,
                    "error": {"code": "BUSY", "message": "沙箱执行槽位繁忙，请稍后重试"},
                }
            )
            return
        self._send(200, {"ok": False, "error": {"code": "BUSY", "message": "沙箱执行槽位繁忙，请稍后重试"}})

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
        self._begin_stream()
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
