"""依赖注入根。

请求级 TraceContext 禁止缓存在本模块。启动时只回显预算并切换审计存储到 PG。
"""

from __future__ import annotations


def configure_runtime() -> None:
    """进程启动装配：预算回显 + 诊断/审计切到 PostgreSQL。

    禁止在此缓存 TraceContext；禁止装配 Redis 记忆层（阶段 4）。
    """
    from app.harness.feedback.diagnostics import PgAuditStore, reset_audit_store
    from app.harness.feedback.publisher import PgAuditPublisher, reset_publisher
    from app.harness.orchestration.budgets import echo_budget_config

    echo_budget_config()
    reset_audit_store(store=PgAuditStore())
    reset_publisher(store=PgAuditPublisher())
