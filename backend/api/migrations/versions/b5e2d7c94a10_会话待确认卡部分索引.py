"""会话待确认卡部分索引

Revision ID: b5e2d7c94a10
Revises: 7c80d0e5b82b
Create Date: 2026-10-29 11:20:00.000000

审批卡 TTL 扫描（``_expire_overdue_approvals_once``，每 30s 一轮）以
``pending_confirm IS NOT NULL`` 为过滤条件遍历 ``sessions`` 全表。绝大多数会话
没有待确认卡，部分索引把该扫描收敛为索引扫描。

索引键使用主键 ``id`` 而非 JSONB 值：确认卡含完整 TaskSpec，整值入 btree 会因超过
单行约 2704 字节上限而写入失败。同时把历史上被 ORM 写成 JSON ``null`` 的值归一为 SQL NULL。
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
    """归一历史 JSON null，并创建仅覆盖待确认卡会话的部分索引。"""
    op.execute("UPDATE sessions SET pending_confirm = NULL WHERE jsonb_typeof(pending_confirm) = 'null'")
    op.create_index(
        "ix_sessions_pending_confirm",
        "sessions",
        ["id"],
        unique=False,
        postgresql_where=sa.text("pending_confirm IS NOT NULL"),
    )


def downgrade() -> None:
    """回滚部分索引。"""
    op.drop_index("ix_sessions_pending_confirm", table_name="sessions")
