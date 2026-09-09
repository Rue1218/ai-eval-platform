"""七节点循环独立配置，不读取环境变量、全局 Settings 或供应商密钥。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopSettings:
    """运行限额沿用源字段；模型请求可由每回合模板完整覆盖。"""

    dsh_provider: str = "deepseek"
    dsh_model: str = ""
    dsh_max_tokens: int = 8192
    dsh_reasoning_effort: str = "high"
    dsh_max_steps: int = 16
    dsh_model_max_retries: int = 2
    dsh_model_retry_delay_seconds: float = 0.25
    dsh_approval_timeout_seconds: float = 300.0
    dsh_max_parallel_tool_calls: int = 4
    dsh_require_approval: bool = True

    def __post_init__(self) -> None:
        """拒绝无法执行的预算，允许零步数作为明确的预算耗尽边界。"""
        if self.dsh_max_tokens < 1 or self.dsh_max_parallel_tool_calls < 1:
            raise ValueError("token and tool concurrency limits must be positive")
        if self.dsh_max_steps < 0 or self.dsh_model_max_retries < 0:
            raise ValueError("step and retry limits must not be negative")
        if self.dsh_model_retry_delay_seconds < 0 or self.dsh_approval_timeout_seconds <= 0:
            raise ValueError("retry delay must be nonnegative and approval timeout positive")
        if self.dsh_reasoning_effort not in ("off", "low", "medium", "high", "xhigh", "max"):
            raise ValueError("unsupported reasoning effort")
