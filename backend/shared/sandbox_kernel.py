"""容器内直跑沙箱内核（api 与独立 sandbox runner 共用）。

**不再使用 bwrap**：``bash`` 直接在 runner 容器内以 ``subprocess`` 执行，
容器本身即隔离边界；每次执行用 ``unshare`` 建立命名空间：

- ``mode="isolated"``（档1/2）：``unshare --net --pid --fork --mount-proc``
  → 全新网络命名空间（仅 lo，无内外网）+ 私有 PID 命名空间；
- ``mode="network"``（档3）：``unshare --pid --fork --mount-proc``
  → 保留网络（是否可达公网由 runner 容器网络与受信启动器决定）；
- **终止证据**：私有 PID 命名空间的 PID 1 退出即由内核清空整个命名空间，
  故 ``killpg`` + ``wait`` 返回即 ``termination_evidence="process_exited"``
  （强度等价于原 cgroup v2 执行域）；
- **资源限制**：``bash`` 启动器设置 ``ulimit``（dash 不支持 ``ulimit -u``，
  必须用 ``bash -c``）；命令始终只作 ``$1`` 参数传入，绝不拼进脚本；
- **环境最小化**：只透传 PATH/HOME/LANG 等，**不含 RUNNER_INTERNAL_TOKEN**。

``probe_sandbox`` 冒烟探测 ``unshare`` 可用性；失败或引擎不可用时调用方必须
fail-closed（禁止降级为无命名空间裸执行）。

错误以 ``SandboxError(code, message)`` 表达（code ∈ TIMEOUT/VALIDATION/
INTERNAL/CANCELLED/OUTCOME_UNKNOWN），由调用方映射到各自错误模型。
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger("ai-eval.sandbox_kernel")

# 网络模式（取代原 bwrap 文件效果档位）："isolated" 断网 / "network" 保留网络。
NETWORK_MODES: frozenset[str] = frozenset({"isolated", "network"})

# 过渡兼容：旧 api/legacy 路径可能仍传文件效果档位，一律映射为 isolated
# （新模型下文件边界由容器挂载与档位审批决定，与网络模式解耦）。
_LEGACY_MODE_ALIASES: dict[str, str] = {
    "workspace-write": "isolated",
    "read-only": "isolated",
}

# 命令最小环境：不含 RUNNER_INTERNAL_TOKEN 等凭据；HOME 指向可写 tmpfs。
_MINIMAL_ENV: dict[str, str] = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TERM": "dumb",
    "XDG_CACHE_HOME": "/tmp/.cache",
    "XDG_CONFIG_HOME": "/tmp/.config",
    "XDG_DATA_HOME": "/tmp/.local/share",
}

# 墙钟终止宽限（killpg 后等待进程组回收的上限，秒）。
_TERMINATE_GRACE_S = 2.0


class SandboxError(Exception):
    """沙箱执行错误（code ∈ TIMEOUT/VALIDATION/INTERNAL/CANCELLED/OUTCOME_UNKNOWN）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """沙箱资源限制（ulimit 注入 + 外层墙钟超时兜底）。"""

    memory_kb: int = 262144  # 虚拟内存上限（KB），默认 256MB
    nproc: int = 32  # 最大进程数（防 fork 炸弹）
    cpu_s: int = 10  # CPU 时间上限（秒）


@dataclass
class SandboxExecutionControl:
    """执行取消信号与终止证据载体；旧调用不传入则保持原返回接口。"""

    cancel_event: threading.Event = field(default_factory=threading.Event)
    started: bool = False
    process_tree_terminated: bool = False
    termination_evidence: str | None = None
    exit_code: int | None = None
    # 契约保留字段：容器模型下无 cgroup，恒为 None（客户端/存储结构不变）。
    cgroup_path: str | None = None


def normalize_mode(mode: str | None) -> str:
    """归一化执行模式；旧文件效果档位映射为 isolated，非法值 fail-closed。"""
    value = str(mode or "").strip()
    if value in NETWORK_MODES:
        return value
    if value in _LEGACY_MODE_ALIASES:
        return _LEGACY_MODE_ALIASES[value]
    raise SandboxError("VALIDATION", f"未知沙箱档位：{mode}")


def build_exec_argv(*, cmd: str, mode: str, limits: SandboxLimits) -> list[str]:
    """构造容器内直跑 argv（纯函数，便于单测）。

    - ``isolated``：``unshare --net --pid --fork --mount-proc`` 直接断网 + 私有 pidns；
    - ``network``（档3）：受信启动器建 netns + veth，经 runner 出公网，
      并用 iptables 阻断内网（RFC1918）与容器本地服务（详见 ``_NETWORK_LAUNCHER``）；
    - 受信启动器：``bash -c '<ulimit>; exec bash -c "$1"' bash <cmd>``——
      命令只作 ``$1``，绝不拼进脚本；``ulimit`` 用 bash（dash 无 ``-u``）。
    """
    normalized = normalize_mode(mode)
    launcher = [
        "bash", "-c",
        (
            f"ulimit -v {limits.memory_kb}; ulimit -u {limits.nproc}; "
            f"ulimit -t {limits.cpu_s}; exec bash -c \"$1\""
        ),
        "bash", cmd,
    ]
    if normalized == "network":
        return [
            "bash", "-c", _NETWORK_LAUNCHER, "sandbox-network",
            cmd, str(limits.memory_kb), str(limits.nproc), str(limits.cpu_s),
        ]
    return ["unshare", "--net", "--pid", "--fork", "--mount-proc", *launcher]


# 档3 网络启动器：建独立 netns + veth，经 runner 出公网；iptables 阻断内网与
# 容器本地服务。命令只作位置参数传入，绝不拼进脚本。任一 setup 失败即退出
# （fail-closed，绝不在无隔离下执行）。清理由 EXIT trap 保证（幂等）。
# 依赖：iproute2(ip) + iptables；runner 需 `--sysctl net.ipv4.ip_forward=1`。
_NETWORK_LAUNCHER = r"""
set -eu
cmd="$1"; mem_kb="$2"; nproc="$3"; cpu_s="$4"
idx=$(( ($$ % 250) + 1 ))
ns="aieval-ns-$idx"; veth_h="aieval-h-$idx"; veth_s="aieval-s-$idx"
subnet="10.201.$idx"; host_ip="$subnet.1"; ns_ip="$subnet.2"
cleanup() {
  ip netns del "$ns" 2>/dev/null || true
  ip link del "$veth_h" 2>/dev/null || true
  iptables -t nat -D POSTROUTING -s "$host_ip/30" -j MASQUERADE 2>/dev/null || true
  iptables -D FORWARD -s "$host_ip/30" -j ACCEPT 2>/dev/null || true
  iptables -D FORWARD -s "$host_ip/30" -d 192.168.0.0/16 -j DROP 2>/dev/null || true
  iptables -D FORWARD -s "$host_ip/30" -d 172.16.0.0/12 -j DROP 2>/dev/null || true
  iptables -D FORWARD -s "$host_ip/30" -d 10.0.0.0/8 -j DROP 2>/dev/null || true
  iptables -D INPUT -s "$host_ip/30" -j DROP 2>/dev/null || true
}
trap cleanup EXIT
ip netns add "$ns"
ip link add "$veth_h" type veth peer name "$veth_s"
ip link set "$veth_s" netns "$ns"
ip addr add "$host_ip/30" dev "$veth_h"
ip link set "$veth_h" up
ip netns exec "$ns" ip addr add "$ns_ip/30" dev "$veth_s"
ip netns exec "$ns" ip link set "$veth_s" up
ip netns exec "$ns" ip link set lo up
ip netns exec "$ns" ip route add default via "$host_ip"
iptables -t nat -A POSTROUTING -s "$host_ip/30" -j MASQUERADE
iptables -I FORWARD 1 -s "$host_ip/30" -j ACCEPT
iptables -I FORWARD 1 -s "$host_ip/30" -d 192.168.0.0/16 -j DROP
iptables -I FORWARD 1 -s "$host_ip/30" -d 172.16.0.0/12 -j DROP
iptables -I FORWARD 1 -s "$host_ip/30" -d 10.0.0.0/8 -j DROP
iptables -I INPUT 1 -s "$host_ip/30" -j DROP
ip netns exec "$ns" unshare --pid --fork --mount-proc bash -c "ulimit -v $mem_kb; ulimit -u $nproc; ulimit -t $cpu_s; exec bash -c \"\$1\"" bash "$cmd"
"""


def resolve_workspace_path(path: str, root: str) -> str:
    """校验工作区路径位于 ``root`` 前缀内，返回 canonical 绝对路径供使用。

    接受嵌套 scope（``{root}/<ws>/<folder>/…``），逐段 realpath 后重验前缀
    （符号链接逃逸拒绝），拒相对路径与 ``..`` 段；越界/非法一律抛
    ``SandboxError(VALIDATION)``（fail-closed）。
    """
    if not path or not root:
        raise SandboxError("VALIDATION", "非法工作区路径")
    root_real = os.path.realpath(root)
    abs_path = os.path.abspath(path)
    if abs_path == root_real or not abs_path.startswith(root_real + os.sep):
        raise SandboxError("VALIDATION", "工作区路径越出根目录")
    rel = os.path.relpath(abs_path, root_real)
    if rel == "." or rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        raise SandboxError("VALIDATION", "工作区路径非法")
    # 逐段 realpath 重验：任一中间段为指向前缀外的符号链接即拒绝
    current = root_real
    for segment in rel.split(os.sep):
        current = os.path.realpath(os.path.join(current, segment))
        if current != root_real and not current.startswith(root_real + os.sep):
            raise SandboxError("VALIDATION", "工作区路径含越界符号链接")
    return current


def _terminate(process: subprocess.Popen[str]) -> bool:
    """强杀进程组并回收；返回是否取得「进程树已终止」证据。

    私有 PID 命名空间的 PID 1 退出后由内核清空整个命名空间，故 ``killpg`` +
    ``wait`` 返回即证明整树停止（``process_exited``）。无法在宽限内回收则返回
    False，交由调用方判 ``OUTCOME_UNKNOWN``。
    """
    try:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_S)
    except subprocess.TimeoutExpired:
        return False
    return True


def run_sandboxed(
    cmd: str,
    *,
    sandbox_dir: str,
    mode: str = "isolated",
    timeout_s: float,
    limits: SandboxLimits | None = None,
    bwrap_bin: str | None = None,  # 兼容保留，容器模型下忽略
    max_output_chars: int = 20000,
    on_output: Callable[[str], None] | None = None,
    control: SandboxExecutionControl | None = None,
    cgroup_root: str | None = None,  # 兼容保留，容器模型下忽略
) -> str:
    """在 runner 容器内（可选命名空间隔离）执行命令，返回 stdout；失败抛 SandboxError。

    - ``mode`` ∈ NETWORK_MODES：isolated → ``unshare --net`` 断网；
      network → 保留网络；旧文件效果档位自动映射 isolated；未知档位 fail-closed；
    - 超时/取消：``killpg(SIGKILL)`` 整树清理（PID 1 退出由内核清空 pidns）；
    - 非零退出码：抛 ``SandboxError(VALIDATION)``，附截断的 stderr 摘要；
    - fail-closed：``unshare`` 缺失/被 seccomp 拦截导致启动失败即抛
      ``SandboxError(VALIDATION, "沙箱引擎不可用")``，禁止降级为无隔离执行。
    """
    if control is not None:
        control.process_tree_terminated = True
        control.termination_evidence = "not_started"
        if control.cancel_event.is_set():
            raise SandboxError("CANCELLED", "命令在启动前取消")
    if not cmd.strip():
        raise SandboxError("VALIDATION", "bash 命令为空")
    normalized = normalize_mode(mode)
    limits = limits or SandboxLimits()
    argv = build_exec_argv(cmd=cmd, mode=normalized, limits=limits)
    # 记录脱敏摘要（命令长度与目录，不打印命令原文/密钥）
    logger.info(
        "bash 容器执行 mode=%s len=%d dir=%s timeout=%s",
        normalized, len(cmd), sandbox_dir, timeout_s,
    )
    try:
        if control is not None:
            control.started = True
            control.process_tree_terminated = False
            control.termination_evidence = None
        started = subprocess.Popen(
            argv,
            start_new_session=True,
            cwd=sandbox_dir,
            env=_MINIMAL_ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (FileNotFoundError, OSError) as exc:
        if control is not None:
            control.started = False
            control.process_tree_terminated = True
            control.termination_evidence = "not_started"
        # unshare 缺失/命名空间被拒：fail-closed，禁止降级为无隔离执行
        raise SandboxError("VALIDATION", "沙箱引擎不可用") from exc
    output_parts: list[str] = []
    output_chars = 0

    def drain_stdout() -> None:
        """逐行排空 stdout；即使超出展示上限仍持续读取以避免子进程阻塞。"""
        nonlocal output_chars
        stdout = started.stdout
        if stdout is None:
            return
        try:
            for chunk in iter(stdout.readline, ""):
                remaining = max_output_chars - output_chars
                if remaining <= 0:
                    continue
                safe_chunk = chunk[:remaining]
                if not safe_chunk:
                    continue
                output_parts.append(safe_chunk)
                output_chars += len(safe_chunk)
                if on_output is not None:
                    try:
                        on_output(safe_chunk)
                    except Exception:  # noqa: BLE001 —— 客户端断开不应影响清理
                        logger.info("bash 输出回调失败，继续执行并回收进程")
        finally:
            stdout.close()

    reader = threading.Thread(target=drain_stdout, name="sandbox-stdout", daemon=True)
    if control is not None:
        # 清理覆盖读线程启动、wait 异常、超时和主动取消；取消请求本身不是终止证据。
        reason = None
        try:
            reader.start()
            deadline = time.monotonic() + timeout_s
            while started.poll() is None:
                if control.cancel_event.is_set():
                    reason = "CANCELLED"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "TIMEOUT"
                    break
                try:
                    started.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    continue
        finally:
            control.process_tree_terminated = _terminate(started)
            control.exit_code = started.returncode
            if control.process_tree_terminated:
                control.termination_evidence = "process_exited"
            if reader.ident is not None:
                reader.join(timeout=1.0)
            elif started.stdout is not None:
                started.stdout.close()
        if not control.process_tree_terminated:
            raise SandboxError("OUTCOME_UNKNOWN", "无法证实沙箱进程树已终止")
        if reason is not None:
            raise SandboxError(reason, "命令已取消" if reason == "CANCELLED" else "命令执行超时")
    else:
        reader.start()
        _wait_legacy(started, reader, timeout_s)
    return _sandbox_output(started.returncode, "".join(output_parts))


def _wait_legacy(started: subprocess.Popen[str], reader: threading.Thread, timeout_s: float) -> None:
    """保留旧接口的等待和超时语义（不产生新接口的整树证据）。"""
    try:
        started.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(started.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        started.wait()
        reader.join(timeout=1.0)
        raise SandboxError("TIMEOUT", "命令执行超时") from None
    reader.join(timeout=1.0)


def _sandbox_output(returncode: int | None, stdout: str) -> str:
    """统一输出与非零退出码归因（容器模型下不再有 read-only bind / EROFS）。"""
    if returncode != 0:
        detail = stdout.strip().splitlines()
        snippet = detail[-1][:500] if detail else ""
        raise SandboxError("VALIDATION", f"命令执行失败（退出码 {returncode}）：{snippet}")
    return stdout.strip() or "（无输出）"


def probe_sandbox(timeout_s: float = 5.0) -> bool:
    """冒烟探测 ``unshare`` 命名空间能力；结果进程内缓存。

    用 ``unshare --net --pid --fork --mount-proc true`` 验证可建命名空间；
    被 seccomp 拦截/二进制缺失返回 False，调用方据此 fail-closed。
    """
    global _PROBE_RESULT
    if _PROBE_RESULT is not None:
        return _PROBE_RESULT
    try:
        result = subprocess.run(
            ["unshare", "--net", "--pid", "--fork", "--mount-proc", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
        _PROBE_RESULT = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _PROBE_RESULT = False
    logger.info("unshare 冒烟探测 result=%s", _PROBE_RESULT)
    return _PROBE_RESULT


def reset_probe_cache() -> None:
    """清空冒烟探测缓存（测试用）。"""
    global _PROBE_RESULT
    _PROBE_RESULT = None


_PROBE_RESULT: bool | None = None
