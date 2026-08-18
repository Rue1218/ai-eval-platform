"""报告域：免登分享令牌与基线冻结标记。

Revision ID: e5f92b7d31a8
Revises: d4a81c6e93f2
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Alembic 迁移标识。
revision: str = "e5f92b7d31a8"
down_revision: Union[str, None] = "d4a81c6e93f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """reports 表新增分享令牌、分享过期时间与基线冻结标记。"""
    op.add_column("reports", sa.Column("share_token", sa.String(), nullable=True))
    op.add_column("reports", sa.Column("share_expire_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "reports",
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_reports_share_token", "reports", ["share_token"], unique=False)
    op.alter_column("reports", "is_baseline", server_default=None)


def downgrade() -> None:
    """回滚报告分享与基线字段。"""
    op.drop_index("ix_reports_share_token", table_name="reports")
    op.drop_column("reports", "is_baseline")
    op.drop_column("reports", "share_expire_at")
    op.drop_column("reports", "share_token")
