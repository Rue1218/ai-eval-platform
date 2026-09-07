"""执行选择显式化（dsh 借鉴 #5，无对外契约的内部重构 + 审计面）。

capability seam 借鉴：把「工具/沙箱执行选择」收敛为显式 ``resolve()`` 决策点
——输入（工具名 / Worker / 会话或演练上下文）→ 输出明确 ExecVerdict（放行 /
拒绝 + mode + 可审计 reason），不再散落在多个内联分支：

- ``resolve_bash_engine``：bash 沙箱引擎决策（原 ``registry._bash_handler``
  内联判定）；引擎非 ``bwrap`` 时 fail-closed，禁止降级裸 subprocess；
- ``resolve_worker_visible``：``worker.sandbox`` 的 discover 可见性决策
  （原 ``AgentRegistry.discover`` 静态排除集合 + ``agent_drill_sandbox_enabled``
  布尔分支）；默认 fail-closed 静态排除，仅演练开关放行（演练结束必须复位）。

默认行为逐字节不变：三档单测（常规沙箱 / drill 放行 / 排除 fail-closed）与
``agent_drill_sandbox_enabled=false`` 全量回归为验收门槛。禁止在模块外再出现
第二处同语义内联判断。
"""

from __future__ import annotations

from dataclasses import dataclass

# 沙箱 Worker 标识（AgentRegistry 静态注册；放行属生产红线）
SANDBOX_WORKER_ID = "worker.sandbox"


@dataclass(frozen=True, slots=True)
class ExecVerdict:
    """显式决策结论：allow/mode/reason（reason 供审计与错误文案，禁止堆栈/密钥）。"""

    allow: bool
    mode: str
    reason: str


def resolve_bash_engine(sandbox_engine: str) -> ExecVerdict:
    """bash 执行引擎显式决策（#5）：仅 ``bwrap`` 可执行，其余一律 fail-closed。

    ``sandbox_engine="off"`` / 未知引擎均拒绝 bash（环境缺 bwrap 时同样
    fail-closed，提示改用 read/write/edit，绝不降级为裸 subprocess）。
    """
    if sandbox_engine == "bwrap":
        return ExecVerdict(True, "bwrap", "沙箱引擎已启用（bwrap）")
    return ExecVerdict(
        False,
        "off",
        "bash 工具不可用：沙箱引擎未启用（环境缺 bwrap 时 fail-closed，"
        "请改用 read/write/edit 工具完成文件操作，不要重试 bash）",
    )


def resolve_worker_visible(agent_id: str, *, drill_enabled: bool) -> ExecVerdict:
    """Worker discover 可见性显式决策（#5）：worker.sandbox 默认静态排除。

    code 能力放行属生产红线，须先完成 Linux/Docker 恢复演练与 bwrap 权限
    边界评审；仅 H5 收尾演练开关（``agent_drill_sandbox_enabled``，默认
    False）临时放行以制造危险 bash 审批卡，演练结束必须复位。非沙箱 Worker
    恒可见（常规路径不受本决策影响）。
    """
    if agent_id != SANDBOX_WORKER_ID:
        return ExecVerdict(True, "normal", "非沙箱 Worker，常规可见")
    if drill_enabled:
        return ExecVerdict(
            True,
            "drill",
            "H5 收尾演练放行（agent_drill_sandbox_enabled=true，演练结束必须复位）",
        )
    return ExecVerdict(
        False,
        "fail-closed",
        "worker.sandbox 静态排除：code 能力放行须先完成恢复演练与 bwrap 安全评审",
    )
