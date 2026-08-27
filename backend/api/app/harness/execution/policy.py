"""工具执行策略：权限边界、输出边界与错误恢复的唯一声明。

策略由注册表随工具一同登记。模型只能接收工具说明和输入 Schema；运行时由
ToolNode 与具体 handler 执行策略，浏览器只接收已脱敏的展示投影。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.config import settings


@dataclass(frozen=True, slots=True)
class ToolPermissionPolicy:
    """工具的可执行权限边界。

    项目当前为单团队协作，不为基础工具额外引入角色分叉；会话、附件归属、
    工作区和网络边界仍必须在运行期分别校验，不能只作为展示标签。
    """

    workspace: Literal["none", "read", "write"] = "none"
    network: Literal["none", "public_only"] = "none"
    require_owned_attachment: bool = False
    require_session_task_owner: bool = False
    confirmation_required: bool = False

    def to_payload(self) -> dict[str, object]:
        """投影为不含内部实现的可序列化权限说明。"""
        return {
            "workspace": self.workspace,
            "network": self.network,
            "require_owned_attachment": self.require_owned_attachment,
            "require_session_task_owner": self.require_session_task_owner,
            "confirmation_required": self.confirmation_required,
        }


@dataclass(frozen=True, slots=True)
class ToolRecoveryPolicy:
    """工具失败后的公开恢复策略。

    ``retryable_codes`` 仅表示模型或用户可在修复参数后再试，绝不代表执行器
    自动重复副作用操作。write/edit/bash 默认不自动重跑；沙箱失效与 SSRF 拒绝
    也永远不可重试。
    """

    retryable_codes: frozenset[str] = field(default_factory=frozenset)
    suggested_action: str = "adjust_arguments"
    default_hint: str = "请根据提示调整参数后重试。"
    max_auto_repairs: int = 1

    def to_payload(self, code: str, hint: str = "") -> dict[str, object]:
        """生成供 ToolCard 与模型使用的脱敏恢复信息。"""
        return {
            "retryable": code in self.retryable_codes,
            "suggested_action": self.suggested_action,
            "repair_hint": (hint or self.default_hint)[:500],
            "max_auto_repairs": self.max_auto_repairs,
        }


# 未注册、参数非法等尚未命中工具定义的拒绝路径共用保守策略。
DEFAULT_RECOVERY_POLICY = ToolRecoveryPolicy(
    retryable_codes=frozenset(),
    suggested_action="review_request",
    default_hint="请检查工具名与参数后重新发起请求。",
    max_auto_repairs=0,
)

# 浏览器瞬态工具输出上限与分发块大小：完整 Observation 仍仅留在服务端
# 当前回合。上限读 settings（默认对齐 read 模型窗口，可经环境变量收紧），
# 块大小保持固定以保证 WS 帧粒度稳定。
TOOL_STREAM_CHUNK_CHARS = 800


def stream_max_chars() -> int:
    """单次 ToolCall 浏览器增量累计上限；部署经 TOOL_PREVIEW_MAX_CHARS 调整。"""
    return max(1, int(settings.tool_preview_max_chars))
