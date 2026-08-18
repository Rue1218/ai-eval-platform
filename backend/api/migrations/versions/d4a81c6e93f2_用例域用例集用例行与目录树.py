"""用例域：用例集、用例行与目录树。

Revision ID: d4a81c6e93f2
Revises: b3e71a9c42f6
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 迁移标识。
revision: str = "d4a81c6e93f2"
down_revision: Union[str, None] = "b3e71a9c42f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增用例目录树、用例集与用例行三张表。"""
    # 用例目录树节点表：自引用 parent_id 构成树，删除非空目录由路由层拦截。
    op.create_table(
        "case_folders",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["case_folders.id"], name="fk_case_folders_parent"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_folders_parent_id", "case_folders", ["parent_id"], unique=False)
    op.alter_column("case_folders", "sort_order", server_default=None)
    op.alter_column("case_folders", "created_at", server_default=None)

    # 用例集表：status 三态由检查约束兜底；expires_at 由任务域在进入待确认时写入。
    op.create_table(
        "case_sets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False, server_default="未命名用例集"),
        sa.Column("status", sa.String(), nullable=False, server_default="generated"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("folder_id", sa.String(), nullable=True),
        sa.Column(
            "column_schema",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "checks",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_case_sets_task"),
        sa.ForeignKeyConstraint(["folder_id"], ["case_folders.id"], name="fk_case_sets_folder"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_case_sets_created_by"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('generated', 'confirmed', 'cancelled')", name="ck_case_sets_status"
        ),
    )
    op.create_index("ix_case_sets_task_id", "case_sets", ["task_id"], unique=False)
    op.create_index("ix_case_sets_status", "case_sets", ["status"], unique=False)
    op.alter_column("case_sets", "name", server_default=None)
    op.alter_column("case_sets", "status", server_default=None)
    op.alter_column("case_sets", "generated_count", server_default=None)
    op.alter_column("case_sets", "confirmed_count", server_default=None)
    op.alter_column("case_sets", "column_schema", server_default=None)
    op.alter_column("case_sets", "checks", server_default=None)
    op.alter_column("case_sets", "created_at", server_default=None)
    op.alter_column("case_sets", "updated_at", server_default=None)

    # 用例行表：固定策略字段 + extras 扩展列值，按用例 id 在用例集内 upsert。
    op.create_table(
        "case_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("case_set_id", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("module", sa.String(), nullable=False, server_default=""),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("precondition", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected", sa.Text(), nullable=False, server_default=""),
        sa.Column("test_type", sa.String(), nullable=False, server_default=""),
        sa.Column("mapped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "extras",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["case_set_id"], ["case_sets.id"], name="fk_case_items_case_set"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_items_case_set_id", "case_items", ["case_set_id"], unique=False)
    op.alter_column("case_items", "module", server_default=None)
    op.alter_column("case_items", "precondition", server_default=None)
    op.alter_column("case_items", "steps", server_default=None)
    op.alter_column("case_items", "expected", server_default=None)
    op.alter_column("case_items", "test_type", server_default=None)
    op.alter_column("case_items", "mapped", server_default=None)
    op.alter_column("case_items", "pending_complete", server_default=None)
    op.alter_column("case_items", "extras", server_default=None)
    op.alter_column("case_items", "sort_order", server_default=None)
    op.alter_column("case_items", "created_at", server_default=None)
    op.alter_column("case_items", "updated_at", server_default=None)


def downgrade() -> None:
    """按反向依赖删除用例域的表、约束与索引。"""
    op.drop_index("ix_case_items_case_set_id", table_name="case_items")
    op.drop_table("case_items")

    op.drop_index("ix_case_sets_status", table_name="case_sets")
    op.drop_index("ix_case_sets_task_id", table_name="case_sets")
    op.drop_table("case_sets")

    op.drop_index("ix_case_folders_parent_id", table_name="case_folders")
    op.drop_table("case_folders")
