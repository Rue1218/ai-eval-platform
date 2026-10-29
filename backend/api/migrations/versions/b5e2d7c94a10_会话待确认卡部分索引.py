"""会话待确认卡部分索引

Revision ID: b5e2d7c94a10
Revises: 7c80d0e5b82b
Create Date: 2026-10-29 11:20:00.000000

审批卡 TTL 扫描（``_expire_overdue_approvals_once``，每 30s 一轮）以
``pending_confirm IS NOT NULL`` 为过滤条件遍历 ``sessions`` 全表。绝大多数会话
没有待确认卡，部分索引把该扫描收敛为索引扫描。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 迁移版本标识。
revision: str = "b5e2d7c94a10"
down_revision: str | None = "7c80d0e5b82b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建仅覆盖待确认卡会话的部分索引。"""
    op.create_index(
        "ix_sessions_pending_confirm",
        "sessions",
        ["pending_confirm"],
        unique=False,
        postgresql_where=sa.text("pending_confirm IS NOT NULL"),
    )


def downgrade() -> None:
    """回滚部分索引。"""
    op.drop_index("ix_sessions_pending_confirm", table_name="sessions")
