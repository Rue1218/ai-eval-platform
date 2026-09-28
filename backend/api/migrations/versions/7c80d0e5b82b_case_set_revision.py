"""用例集增加并发修订号

Revision ID: 7c80d0e5b82b
Revises: 110e3362fba3
Create Date: 2026-09-28 16:02:14.630991

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic 迁移版本标识。
revision: str = "7c80d0e5b82b"
down_revision: str | None = "110e3362fba3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为历史用例集填充初始修订号 0。"""
    op.add_column('case_sets', sa.Column('revision', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    """回滚用例集修订号。"""
    op.drop_column('case_sets', 'revision')
