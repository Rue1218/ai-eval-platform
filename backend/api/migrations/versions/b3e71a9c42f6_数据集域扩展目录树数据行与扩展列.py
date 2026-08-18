"""数据集域扩展：目录树、数据行与扩展列。

Revision ID: b3e71a9c42f6
Revises: fc82d384b215
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 迁移标识。
revision: str = "b3e71a9c42f6"
down_revision: Union[str, None] = "fc82d384b215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增目录树与数据行表，并为 datasets 补齐 M2 扩展字段。"""
    # 目录树节点表：自引用 parent_id 构成树，删除非空目录由路由层拦截。
    op.create_table(
        "dataset_folders",
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
            ["parent_id"], ["dataset_folders.id"], name="fk_dataset_folders_parent"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_folders_parent_id", "dataset_folders", ["parent_id"], unique=False)
    op.alter_column("dataset_folders", "sort_order", server_default=None)
    op.alter_column("dataset_folders", "created_at", server_default=None)

    # 数据行表：固定三元组 + extras 扩展列值，按 (dataset_id, row_no) 唯一 upsert。
    op.create_table(
        "dataset_rows",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("reference", sa.Text(), nullable=False, server_default=""),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "extras",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("pending_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_case_id", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], name="fk_dataset_rows_dataset"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "row_no", name="uq_dataset_rows_dataset_row_no"),
    )
    op.create_index("ix_dataset_rows_dataset_id", "dataset_rows", ["dataset_id"], unique=False)
    op.alter_column("dataset_rows", "question", server_default=None)
    op.alter_column("dataset_rows", "reference", server_default=None)
    op.alter_column("dataset_rows", "extras", server_default=None)
    op.alter_column("dataset_rows", "pending_complete", server_default=None)
    op.alter_column("dataset_rows", "created_at", server_default=None)
    op.alter_column("dataset_rows", "updated_at", server_default=None)

    # datasets 扩展列：先带 server_default 回填存量行，再去除写入默认值。
    op.add_column(
        "datasets",
        sa.Column("metric", sa.String(), nullable=False, server_default="contain"),
    )
    op.add_column("datasets", sa.Column("folder_id", sa.String(), nullable=True))
    op.add_column(
        "datasets",
        sa.Column(
            "column_schema",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "datasets",
        sa.Column("pending_complete_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_datasets_folder", "datasets", "dataset_folders", ["folder_id"], ["id"]
    )
    op.alter_column("datasets", "metric", server_default=None)
    op.alter_column("datasets", "column_schema", server_default=None)
    op.alter_column("datasets", "pending_complete_count", server_default=None)


def downgrade() -> None:
    """按反向依赖删除数据集域扩展的表、约束与字段。"""
    op.drop_constraint("fk_datasets_folder", "datasets", type_="foreignkey")
    op.drop_column("datasets", "pending_complete_count")
    op.drop_column("datasets", "column_schema")
    op.drop_column("datasets", "folder_id")
    op.drop_column("datasets", "metric")

    op.drop_index("ix_dataset_rows_dataset_id", table_name="dataset_rows")
    op.drop_table("dataset_rows")

    op.drop_index("ix_dataset_folders_parent_id", table_name="dataset_folders")
    op.drop_table("dataset_folders")
