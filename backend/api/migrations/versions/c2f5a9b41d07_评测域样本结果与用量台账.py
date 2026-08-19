"""评测域：样本级结果与用量台账。

Revision ID: c2f5a9b41d07
Revises: e5f92b7d31a8
Create Date: 2026-08-19

由 Worker 在 benchmark 真实执行时写入：
- ``eval_items`` 按「任务 × 协议档 × 行号」唯一，支持按行断点续跑；
- ``usage_ledger`` 按「任务 × 协议档」累计 token 与估算费用，供预算熔断与报告展示。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 迁移标识。
revision: str = "c2f5a9b41d07"
down_revision: Union[str, None] = "e5f92b7d31a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增样本级结果表与用量台账表。"""
    # 样本级结果：唯一键 (task_id, profile_id, row_no) 支撑断点续跑按行跳过
    op.create_table(
        "eval_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("exact", sa.Float(), nullable=True),
        sa.Column("rouge_l", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_eval_items_task"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "profile_id", "row_no", name="uq_eval_items_task_profile_row"),
    )
    op.create_index("ix_eval_items_task_id", "eval_items", ["task_id"], unique=False)
    op.create_index(
        "ix_eval_items_task_profile", "eval_items", ["task_id", "profile_id"], unique=False
    )

    # 用量台账：唯一键 (task_id, profile_id) 支撑逐调用累加 upsert
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False),
        sa.Column("est_cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_usage_ledger_task"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "profile_id", name="uq_usage_ledger_task_profile"),
    )
    op.create_index("ix_usage_ledger_task_id", "usage_ledger", ["task_id"], unique=False)


def downgrade() -> None:
    """回滚样本级结果表与用量台账表。"""
    op.drop_index("ix_usage_ledger_task_id", table_name="usage_ledger")
    op.drop_table("usage_ledger")
    op.drop_index("ix_eval_items_task_profile", table_name="eval_items")
    op.drop_index("ix_eval_items_task_id", table_name="eval_items")
    op.drop_table("eval_items")
