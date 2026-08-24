"""新增 Harness 检查点表（LangGraph Checkpointer PG 持久化，M3 阶段 3）。

Revision ID: a1f3c5e7b9d1
Revises: a7b8c9d0e1f2
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1f3c5e7b9d1"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建检查点与检查点写入表（框架基础设施表，无 ORM 模型）。"""
    op.create_table(
        "harness_checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("checkpoint", sa.LargeBinary(), nullable=False),
        sa.Column("metadata", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_table(
        "harness_checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    )
    op.create_index(
        "ix_harness_checkpoints_thread",
        "harness_checkpoints",
        ["thread_id", "checkpoint_ns"],
    )


def downgrade() -> None:
    """回滚检查点表。"""
    op.drop_index("ix_harness_checkpoints_thread", table_name="harness_checkpoints")
    op.drop_table("harness_checkpoint_writes")
    op.drop_table("harness_checkpoints")
