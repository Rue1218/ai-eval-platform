"""记忆层运行装配：SDK 只在 memory 包创建，Context/编排只接收 MemoryPort。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.harness.contracts.memory import MemoryPort

from .conversation_store import ConversationStore
from .long_term_pgvector import PgvectorMemoryStore
from .ports import CompositeMemoryPort
from .retention import MemoryRetention
from .short_term_redis import RedisMemoryPort


def build_memory_port(db: Session, *, with_redis: bool | None = None) -> MemoryPort:
    """按运行配置组装短期 Redis 与长期 PostgreSQL。

    ``with_redis`` 缺省时随配置 ``harness_memory_short_term_enabled``；
    测试可显式传 False 关闭短期 Port。
    """
    use_redis = (
        settings.harness_memory_short_term_enabled if with_redis is None else with_redis
    )
    short_term = (
        RedisMemoryPort.from_url(
            settings.redis_url,
            retention=MemoryRetention(settings.harness_memory_ttl_seconds),
        )
        if use_redis
        else None
    )
    return CompositeMemoryPort(
        short_term=short_term,
        conversation=ConversationStore(db),
        knowledge=PgvectorMemoryStore(db),
    )
