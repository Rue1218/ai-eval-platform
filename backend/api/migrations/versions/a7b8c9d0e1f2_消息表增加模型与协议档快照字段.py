"""消息表增加模型与协议档快照字段。

Revision ID: a7b8c9d0e1f2
Revises: d9f4a6c2e801
Create Date: 2026-08-23 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision 标识符由 Alembic 使用。
revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "d9f4a6c2e801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """messages 表新增 model_name, profile_id, profile_name, provider 字段供模型展示快照。"""
    op.add_column("messages", sa.Column("model_name", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("profile_id", sa.String(length=64), nullable=True))
    op.add_column("messages", sa.Column("profile_name", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("provider", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """回滚消息表模型与协议档快照字段。"""
    op.drop_column("messages", "provider")
    op.drop_column("messages", "profile_name")
    op.drop_column("messages", "profile_id")
    op.drop_column("messages", "model_name")
