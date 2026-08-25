"""用例行扩展子模块与功能点列。

Revision ID: d5b2f7e9a3c1
Revises: c3a7e9b1d5f2
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Alembic 迁移标识。
revision: str = "d5b2f7e9a3c1"
down_revision: Union[str, None] = "c3a7e9b1d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """case_items 增加子模块/功能点两列（先用空串回填存量行，再去除默认值）。"""
    op.add_column("case_items", sa.Column("submodule", sa.String(), nullable=False, server_default=""))
    op.add_column("case_items", sa.Column("feature_point", sa.String(), nullable=False, server_default=""))
    op.alter_column("case_items", "submodule", server_default=None)
    op.alter_column("case_items", "feature_point", server_default=None)


def downgrade() -> None:
    """移除子模块/功能点两列。"""
    op.drop_column("case_items", "feature_point")
    op.drop_column("case_items", "submodule")
