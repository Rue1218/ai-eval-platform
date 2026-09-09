"""新会话默认使用 AgentLoop

Revision ID: 8f9a2c4d6e01
Revises: 77586e897dae
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f9a2c4d6e01"
down_revision: str | None = "77586e897dae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅更新数据库默认值，历史 legacy 行保留原协议以便只读回放。"""
    op.alter_column(
        "sessions",
        "engine_version",
        existing_type=sa.String(),
        existing_nullable=False,
        server_default="agent_loop_v2",
    )


def downgrade() -> None:
    """回退默认值；已经创建的 AgentLoop 会话不在迁移中改写。"""
    op.alter_column(
        "sessions",
        "engine_version",
        existing_type=sa.String(),
        existing_nullable=False,
        server_default="legacy",
    )
