"""messages 增加 turn_stats 观测指标列。

Revision ID: c52e8fa1b340
Revises: a9c41b7e2d10
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 迁移标识。
revision: str = "c52e8fa1b340"
down_revision: Union[str, None] = "a9c41b7e2d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """assistant 消息落 turn 级指标(模型轮数/token/工具成败),存量行保持 NULL。"""
    op.add_column(
        "messages",
        sa.Column("turn_stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "turn_stats")
