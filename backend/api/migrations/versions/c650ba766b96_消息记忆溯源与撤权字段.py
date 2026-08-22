"""消息记忆溯源与撤权字段。

Revision ID: c650ba766b96
Revises: b7e4a1c90825
Create Date: 2026-08-22 14:00:56.945401

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c650ba766b96"
down_revision: Union[str, None] = "b7e4a1c90825"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为消息补 trace 溯源与记忆撤权标记；既有历史保留且默认可召回。"""
    op.add_column("messages", sa.Column("origin_trace_id", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("origin_span_id", sa.String(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("memory_forgotten", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_messages_origin_trace_id", "messages", ["origin_trace_id"], unique=False)


def downgrade() -> None:
    """回滚记忆层新增列，不删除既有消息正文与会话历史。"""
    op.drop_index("ix_messages_origin_trace_id", table_name="messages")
    op.drop_column("messages", "memory_forgotten")
    op.drop_column("messages", "origin_span_id")
    op.drop_column("messages", "origin_trace_id")
