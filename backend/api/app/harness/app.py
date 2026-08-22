"""依赖注入根。

请求级 TraceContext 禁止缓存在本模块。启动时只回显预算并切换审计存储到 PG。
"""

from __future__ import annotations


def configure_runtime() -> None:
    """进程启动装配：预算回显、审计 PostgreSQL 与记忆 Port。

    禁止在此缓存 TraceContext；Redis 客户端可复用，但请求级数据库 Session 必须按请求注入。
    """
    from app.harness.feedback.diagnostics import PgAuditStore, reset_audit_store
    from app.harness.feedback.publisher import PgAuditPublisher, reset_publisher
    from app.harness.memory.runtime import configure_memory_runtime
    from app.harness.orchestration.budgets import echo_budget_config

    echo_budget_config()
    reset_audit_store(store=PgAuditStore())
    reset_publisher(store=PgAuditPublisher())
    configure_memory_runtime()
