"""协议档增加 context_window 上下文窗口字段。

Revision ID: a1b2c3d4e5f6
Revises: f7c3e91a2b04
Create Date: 2026-08-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7c3e91a2b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """protocol_profiles 增加 context_window 字段（默认 200,000 Tokens）。"""
    op.add_column(
        "protocol_profiles",
        sa.Column("context_window", sa.Integer(), nullable=False, server_default="200000"),
    )


def downgrade() -> None:
    """回滚 protocol_profiles context_window 字段。"""
    op.drop_column("protocol_profiles", "context_window")
