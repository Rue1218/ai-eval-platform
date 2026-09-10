"""新 Agent Loop 的异步 Runner 客户端；未知结果交由持久 guard 隔离，不重试执行。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any
from uuid import UUID

import httpx
from shared.sandbox_kernel import SandboxLimits

# 可接受的「进程树已终止」证据：not_started（启动前/墓碑）与 process_exited
# （容器内直跑，私有 PID 命名空间 PID 1 退出由内核清空整树）。旧 cgroup_empty
# 已随 bwrap 移除。
_TERMINATED_EVIDENCE = frozenset({"not_started", "process_exited"})


@dataclass(frozen=True)
class RunnerRequest:
    """可信 API 从会话绑定生成的请求；ID 和实例代次须在 dispatch 前持久化。"""

    execution_id: str
    session_id: str
    turn_id: str
    call_id: str
    command: str
    workspace_root: str
    mode: str = "isolated"
    timeout_s: float = 15.0
    limits: SandboxLimits = field(default_factory=SandboxLimits)
    max_output_chars: int = 20000

    def payload(self) -> dict[str, Any]:
        """只发送已声明字段，不携带客户端 cwd 或任何降级执行开关。"""
        return {
            "execution_id": str(UUID(self.execution_id)),
            "session_id": self.session_id, "turn_id": self.turn_id, "call_id": self.call_id,
            "command": self.command,
            "policy": {"workspace_root": self.workspace_root, "mode": self.mode},
            "timeout_s": self.timeout_s, "limits": asdict(self.limits),
            "max_output_chars": self.max_output_chars,
        }

    @property
    def fingerprint(self) -> str:
        """与 Runner 使用相同原始请求摘要，用于拒绝误配的成功回执。"""
        return sha256(json.dumps(self.payload(), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class RunnerResult:
    """执行结果与停止证据分离；guard 只在可信证据到达后释放。"""

    execution_id: str
    runner_instance_id: str
    status: str
    process_tree_terminated: bool = False
    termination_evidence: str | None = None
    execution_started: bool | None = None
    request_fingerprint: str | None = None
    exit_code: int | None = None
    output: str = ""
    error_code: str | None = None
    message: str = ""
    cgroup_path: str | None = None

    @property
    def guard_releasable(self) -> bool:
        """请求已结束不等于执行已停止；没有证据时必须保持隔离。"""
        return self.status != "running" and self.process_tree_terminated and self.termination_evidence in _TERMINATED_EVIDENCE


class LoopRunnerClient:
    """复用 httpx 连接池；提交一次，后续仅查询或取消，不隐式重新派发。"""

    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None,
                 http_timeout_s: float = 5.0, poll_interval_s: float = 0.1, cancel_grace_s: float = 5.0) -> None:
        """使用显式内部令牌和有界超时，不生成凭据或读取代理环境。"""
        if not token:
            raise ValueError("Runner 内部认证令牌未配置")
        if min(http_timeout_s, poll_interval_s, cancel_grace_s) <= 0:
            raise ValueError("Runner 客户端超时必须为正数")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        self.http_timeout_s = http_timeout_s
        self.poll_interval_s = poll_interval_s
        self.cancel_grace_s = cancel_grace_s

    async def aclose(self) -> None:
        """仅释放自行创建的连接池，注入客户端由调用方管理。"""
        if self._owns_client:
            await self._client.aclose()

    async def instance_id(self) -> str:
        """派发前获取并持久化代次；恢复旧执行时禁止重新获取代次再重发。"""
        response = await self._client.get(f"{self.base_url}/executions",
            headers={"Authorization": f"Bearer {self._token}"}, timeout=self.http_timeout_s, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if data.get("protocol_version") != 1:
            raise ValueError("Runner 执行协议版本不兼容")
        return str(UUID(data["runner_instance_id"]))

    @staticmethod
    def _unknown(execution_id: str, instance_id: str, code: str = "OUTCOME_UNKNOWN") -> RunnerResult:
        """连接失败、坏回执或代次变化不提供停止证据，禁止用其释放 guard。"""
        return RunnerResult(execution_id, instance_id, "outcome_unknown", error_code=code,
                            message="无法证实远端执行结果，请保持工作区隔离")

    async def _request(self, method: str, path: str, execution_id: str, instance_id: str,
                       *, payload: dict[str, Any] | None = None, fingerprint: str | None = None) -> RunnerResult:
        """严格校验身份、状态与停止证据，HTTP 成功本身不表示命令成功。"""
        try:
            response = await self._client.request(method, f"{self.base_url}{path}", json=payload,
                headers={"Authorization": f"Bearer {self._token}", "X-Runner-Instance-ID": instance_id},
                timeout=self.http_timeout_s, follow_redirects=False)
            if response.status_code == 409 and response.json().get("error", {}).get("code") == "CONFLICT":
                return self._unknown(execution_id, instance_id, "CONFLICT")
            response.raise_for_status()
            data = response.json()
            if data.get("execution_id") != execution_id or data.get("runner_instance_id") != instance_id:
                return self._unknown(execution_id, instance_id, "RECEIPT_MISMATCH")
            status = data.get("status")
            if status not in {"running", "succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown"}:
                return self._unknown(execution_id, instance_id)
            evidence = data.get("termination_evidence")
            terminated = data.get("process_tree_terminated") is True
            if terminated and ((evidence == "not_started" and data.get("execution_started") is not False)
                               or (evidence == "process_exited" and data.get("execution_started") is not True)):
                return self._unknown(execution_id, instance_id)
            if status not in {"running", "outcome_unknown"} and (not terminated or evidence not in _TERMINATED_EVIDENCE):
                return self._unknown(execution_id, instance_id)
            if (status == "not_started" and evidence != "not_started") or (status == "cancelled" and evidence != "process_exited"):
                return self._unknown(execution_id, instance_id)
            if status == "succeeded" and (evidence != "process_exited" or data.get("exit_code") != 0):
                return self._unknown(execution_id, instance_id)
            if fingerprint is not None and data.get("request_fingerprint") != fingerprint:
                # 取消先到产生的墓碑没有请求摘要，只证明此代次的 ID 永远不会启动。
                if not (status == "not_started" and evidence == "not_started" and data.get("request_fingerprint") is None):
                    return self._unknown(execution_id, instance_id, "RECEIPT_MISMATCH")
            error = data.get("error") or {}
            return RunnerResult(execution_id, instance_id, status, terminated, evidence,
                data.get("execution_started"), data.get("request_fingerprint"), data.get("exit_code"),
                str(data.get("output") or ""), error.get("code"), str(error.get("message") or ""), data.get("cgroup_path"))
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return self._unknown(execution_id, instance_id)

    async def submit(self, request: RunnerRequest, runner_instance_id: str) -> RunnerResult:
        """单次派发；同 ID 重发由服务端幂等围栏拦截，客户端不自动重试。"""
        return await self._request("POST", "/executions", str(UUID(request.execution_id)), runner_instance_id,
                                   payload=request.payload(), fingerprint=request.fingerprint)

    async def status(self, execution_id: str, runner_instance_id: str, *, fingerprint: str | None = None) -> RunnerResult:
        """按原 Runner 代次查询，查无记录仍是 outcome_unknown。"""
        execution_id = str(UUID(execution_id))
        return await self._request("GET", f"/executions/{execution_id}", execution_id,
                                   runner_instance_id, fingerprint=fingerprint)

    async def cancel(self, execution_id: str, runner_instance_id: str, *, fingerprint: str | None = None) -> RunnerResult:
        """请求取消只设置远端信号，running 响应不得当成 cancelled。"""
        execution_id = str(UUID(execution_id))
        return await self._request("POST", f"/executions/{execution_id}/cancel", execution_id,
                                   runner_instance_id, fingerprint=fingerprint)

    async def _cancel_and_wait(self, request: RunnerRequest, instance_id: str) -> RunnerResult:
        """有界 drain；时间耗尽也不伪造远端停止，交由主循环持久化 guard。"""
        try:
            async with asyncio.timeout(self.cancel_grace_s):
                result = await self.cancel(request.execution_id, instance_id, fingerprint=request.fingerprint)
                while result.status == "running":
                    await asyncio.sleep(self.poll_interval_s)
                    result = await self.status(request.execution_id, instance_id, fingerprint=request.fingerprint)
                return result
        except TimeoutError:
            return self._unknown(request.execution_id, instance_id)

    async def run(self, request: RunnerRequest, runner_instance_id: str, *, cancel_event: asyncio.Event | None = None,
                  wait_timeout_s: float | None = None) -> RunnerResult:
        """等待实际回执；协作取消或 Task.cancel 均 drain 后返回可持久化结果。

        调用方须先登记 guard，拿到返回值后再关闭 turn；Task.cancel 在本边界被
        消费以便返回取消/未知收据，不能把 Python 任务取消当作远端已停止。
        """
        try:
            async with asyncio.timeout(wait_timeout_s if wait_timeout_s is not None else request.timeout_s + 10):
                if cancel_event is not None and cancel_event.is_set():
                    return await self._cancel_and_wait(request, runner_instance_id)
                result = await self.submit(request, runner_instance_id)
                while result.status == "running":
                    if cancel_event is not None and cancel_event.is_set():
                        return await self._cancel_and_wait(request, runner_instance_id)
                    await asyncio.sleep(self.poll_interval_s)
                    result = await self.status(request.execution_id, runner_instance_id, fingerprint=request.fingerprint)
                if result.status != "outcome_unknown":
                    return result
                if result.error_code in {"CONFLICT", "RECEIPT_MISMATCH"}:
                    return result
        except (TimeoutError, asyncio.CancelledError):
            pass
        # 保留清理 Task 的引用；重复取消不会取消远端清理请求或丢弃 guard 收据。
        cleanup = asyncio.create_task(self._cancel_and_wait(request, runner_instance_id))
        while True:
            try:
                return await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                if cleanup.done():
                    # 服务关闭可能连清理任务一起取消；不能对已取消任务无限自旋。
                    return self._unknown(request.execution_id, runner_instance_id) if cleanup.cancelled() else cleanup.result()
                continue
