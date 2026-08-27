"""协议档增加 max_output_tokens 模型输出上限字段。

Revision ID: e7a1c3f52b48
Revises: c52e8fa1b340
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7a1c3f52b48"
down_revision: Union[str, None] = "c52e8fa1b340"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """protocol_profiles 增加 max_output_tokens 字段（默认 8192，保持既有行为）。"""
    op.add_column(
        "protocol_profiles",
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="8192"),
    )


def downgrade() -> None:
    """回滚 protocol_profiles max_output_tokens 字段。"""
    op.drop_column("protocol_profiles", "max_output_tokens")
