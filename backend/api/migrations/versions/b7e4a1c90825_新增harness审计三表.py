"""新增 Harness 链路审计三表。

Revision ID: b7e4a1c90825
Revises: cf9e2d5b7a01
Create Date: 2026-08-21 23:10:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4a1c90825"
down_revision: Union[str, None] = "cf9e2d5b7a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 harness_turns / harness_spans / harness_diagnostics，审计只落 PostgreSQL。"""
    op.create_table(
        "harness_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", name="uq_harness_turns_trace_id"),
    )
    op.create_index("ix_harness_turns_trace_id", "harness_turns", ["trace_id"], unique=False)
    op.create_index("ix_harness_turns_turn_id", "harness_turns", ["turn_id"], unique=False)
    op.create_index("ix_harness_turns_session_id", "harness_turns", ["session_id"], unique=False)

    op.create_table(
        "harness_spans",
        sa.Column("span_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("parent_span_id", sa.String(), nullable=True),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("span_id"),
    )
    op.create_index("ix_harness_spans_trace_id", "harness_spans", ["trace_id"], unique=False)

    op.create_table(
        "harness_diagnostics",
        sa.Column("diagnostic_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("span_id", sa.String(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("diagnostic_id"),
    )
    op.create_index(
        "ix_harness_diagnostics_trace_id", "harness_diagnostics", ["trace_id"], unique=False
    )


def downgrade() -> None:
    """回滚审计三表。"""
    op.drop_index("ix_harness_diagnostics_trace_id", table_name="harness_diagnostics")
    op.drop_table("harness_diagnostics")
    op.drop_index("ix_harness_spans_trace_id", table_name="harness_spans")
    op.drop_table("harness_spans")
    op.drop_index("ix_harness_turns_session_id", table_name="harness_turns")
    op.drop_index("ix_harness_turns_turn_id", table_name="harness_turns")
    op.drop_index("ix_harness_turns_trace_id", table_name="harness_turns")
    op.drop_table("harness_turns")
