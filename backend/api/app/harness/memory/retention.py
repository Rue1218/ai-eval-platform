"""短期记忆的保留策略；审计表与 /stop 注册表均不在此处处理。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRetention:
    """Redis 短期记录的统一 TTL 配置，避免调用点各自硬编码。"""

    ttl_seconds: int = 86400

    def normalized_ttl(self) -> int:
        """TTL 必须为正整数，异常配置退回一天而不是永久保存。"""
        return self.ttl_seconds if self.ttl_seconds > 0 else 86400
