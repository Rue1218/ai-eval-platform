"""工作区表与会话绑定列（工作区与沙箱设计方案 F1/G1，A V0.4.1 §4.1）。

- 新增 ``workspaces`` 表：id(uuid) / owner_id / name / deleted_at(软删) /
  created_at / updated_at；``name`` 每属主**活跃行**唯一（部分唯一索引，
  软删行占名不阻止复活与重建）。
- ``sessions`` 增 ``workspace_id``（FK ``workspaces.id`` ON DELETE RESTRICT，
  显式解绑后才可 purge；绝不用 SET NULL——静默回落违背 fail-closed）与
  ``scope_path``（工作区内相对子目录，可空）。

Revision ID: e8f1a2b3c4d5
Revises: c3d5e7f9a1b2
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f1a2b3c4d5"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建工作区表并为会话加绑定列。"""
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_index("ix_workspaces_deleted_at", "workspaces", ["deleted_at"])
    op.create_index(
        "uq_workspaces_owner_name_active",
        "workspaces",
        ["owner_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "workspace_id",
            sa.String(),
            nullable=True,
        ),
    )
    op.add_column("sessions", sa.Column("scope_path", sa.String(), nullable=True))
    op.create_index("ix_sessions_workspace_id", "sessions", ["workspace_id"])
    op.create_foreign_key(
        "fk_sessions_workspace_id",
        "sessions",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """回滚工作区表与会话绑定列。"""
    op.drop_constraint("fk_sessions_workspace_id", "sessions", type_="foreignkey")
    op.drop_index("ix_sessions_workspace_id", table_name="sessions")
    op.drop_column("sessions", "scope_path")
    op.drop_column("sessions", "workspace_id")
    op.drop_index("uq_workspaces_owner_name_active", table_name="workspaces")
    op.drop_index("ix_workspaces_deleted_at", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_table("workspaces")
