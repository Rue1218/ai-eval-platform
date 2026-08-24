"""评测样本增加 LLM 裁判打分列。

Revision ID: a2b4c6d8e0f2
Revises: a1f3c5e7b9d1
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a2b4c6d8e0f2"
down_revision: Union[str, None] = "a1f3c5e7b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """eval_items 增加裁判打分与理由两列（双模型对比测评的 LLM 裁判分）。"""
    op.add_column("eval_items", sa.Column("judge_score", sa.Integer(), nullable=True))
    op.add_column("eval_items", sa.Column("judge_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚：删除裁判打分与理由两列。"""
    op.drop_column("eval_items", "judge_reason")
    op.drop_column("eval_items", "judge_score")
