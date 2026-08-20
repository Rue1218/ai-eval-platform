"""助手消息增加回复耗时字段。

Revision ID: cf9e2d5b7a01
Revises: 4812e1f50613
Create Date: 2026-08-20 14:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cf9e2d5b7a01"
down_revision: Union[str, None] = "4812e1f50613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """messages 表新增 latency_ms：assistant 交付句回复耗时（毫秒），存量消息为 NULL。"""
    op.add_column("messages", sa.Column("latency_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    """回滚回复耗时字段。"""
    op.drop_column("messages", "latency_ms")
