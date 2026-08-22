"""记忆 Port 运行时装配：仅此处读取 Redis 配置，按请求组合 PostgreSQL 对话归档。"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.agent.log import agent_trace
from app.config import settings
from app.harness.contracts.memory import MemoryPort

from .conversation_store import ConversationMemoryPort
from .ports import CompositeMemoryPort
from .retention import MemoryRetention
from .short_term_redis import RedisMemoryPort

_SHORT_TERM_PORT: MemoryPort | None = None


def configure_memory_runtime() -> None:
    """启动时装配可复用 Redis 客户端；请求级数据库 Session 不得缓存在全局。"""
    global _SHORT_TERM_PORT
    redis_url = settings.redis_url.strip()
    if not redis_url:
        _SHORT_TERM_PORT = None
        agent_trace("memory Redis未配置，仅装配PG对话归档")
        return
    _SHORT_TERM_PORT = RedisMemoryPort.from_url(
        redis_url,
        retention=MemoryRetention(ttl_seconds=settings.memory_redis_ttl_seconds),
    )
    agent_trace("memory Redis短期Port已装配")


def memory_port_for_session(db: DbSession) -> MemoryPort:
    """为单请求创建组合 Port；短期 Redis 可复用，对话归档必须绑定当前 DB Session。"""
    return CompositeMemoryPort(
        short_term=_SHORT_TERM_PORT,
        conversation=ConversationMemoryPort(db=db, tenant_id=settings.memory_tenant_id),
    )


def reset_memory_runtime(*, short_term: MemoryPort | None = None) -> None:
    """测试替换全局短期 Port；生产代码只能通过 configure_memory_runtime 装配。"""
    global _SHORT_TERM_PORT
    _SHORT_TERM_PORT = short_term
