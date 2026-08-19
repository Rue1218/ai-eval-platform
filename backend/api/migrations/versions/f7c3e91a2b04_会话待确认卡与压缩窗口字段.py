"""会话表增加 pending_confirm / compact 窗口字段（Agent 说明书 §16.1 / §16.6）。

Revision ID: f7c3e91a2b04
Revises: c2f5a9b41d07
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f7c3e91a2b04"
down_revision: Union[str, None] = "c2f5a9b41d07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """sessions 增加待确认卡、压缩摘要与窗口游标。"""
    op.add_column("sessions", sa.Column("pending_confirm", JSONB(), nullable=True))
    op.add_column("sessions", sa.Column("compact_summary", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("compact_keep_from", sa.String(), nullable=True))


def downgrade() -> None:
    """回滚会话 Harness 增量列。"""
    op.drop_column("sessions", "compact_keep_from")
    op.drop_column("sessions", "compact_summary")
    op.drop_column("sessions", "pending_confirm")
