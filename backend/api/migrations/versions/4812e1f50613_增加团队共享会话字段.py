"""增加团队共享会话字段。

Revision ID: 4812e1f50613
Revises: f7c3e91a2b04
Create Date: 2026-08-20 11:41:23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4812e1f50613"
down_revision: Union[str, None] = "f7c3e91a2b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加共享范围、软删除和协作者可追溯字段，并回填存量作者。"""
    op.add_column(
        "sessions",
        sa.Column(
            "visibility",
            sa.String(),
            server_default=sa.text("'private'"),
            nullable=False,
        ),
    )
    op.add_column("sessions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("pending_confirm_author_id", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        "ck_sessions_visibility", "sessions", "visibility IN ('private', 'team')"
    )
    op.create_index("ix_sessions_deleted_at", "sessions", ["deleted_at"], unique=False)
    op.create_index(
        "ix_sessions_visibility_deleted_at",
        "sessions",
        ["visibility", "deleted_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_sessions_pending_confirm_author_id_users",
        "sessions",
        "users",
        ["pending_confirm_author_id"],
        ["id"],
    )

    op.add_column("messages", sa.Column("author_id", sa.String(), nullable=True))
    op.add_column(
        "messages", sa.Column("client_message_id", sa.String(length=128), nullable=True)
    )
    op.create_index("ix_messages_author_id", "messages", ["author_id"], unique=False)
    op.create_unique_constraint(
        "uq_messages_session_client_message",
        "messages",
        ["session_id", "client_message_id"],
    )
    op.create_foreign_key(
        "fk_messages_author_id_users",
        "messages",
        "users",
        ["author_id"],
        ["id"],
    )

    # 存量用户消息过去只记录会话 owner；迁移后以 owner 作为可回放的历史作者。
    op.execute(
        """
        UPDATE messages AS m
        SET author_id = s.user_id
        FROM sessions AS s
        WHERE m.session_id = s.id
          AND m.role = 'user'
          AND m.author_id IS NULL
        """
    )
    # 升级时已存在的确认卡同样由原会话创建者继续控制，避免卡片无人可确认。
    op.execute(
        """
        UPDATE sessions
        SET pending_confirm_author_id = user_id
        WHERE pending_confirm IS NOT NULL
          AND pending_confirm_author_id IS NULL
        """
    )


def downgrade() -> None:
    """回滚团队共享字段；历史任务、消息和审计记录不物理删除。"""
    op.drop_constraint("fk_messages_author_id_users", "messages", type_="foreignkey")
    op.drop_constraint(
        "uq_messages_session_client_message", "messages", type_="unique"
    )
    op.drop_index("ix_messages_author_id", table_name="messages")
    op.drop_column("messages", "client_message_id")
    op.drop_column("messages", "author_id")

    op.drop_constraint(
        "fk_sessions_pending_confirm_author_id_users",
        "sessions",
        type_="foreignkey",
    )
    op.drop_index("ix_sessions_visibility_deleted_at", table_name="sessions")
    op.drop_index("ix_sessions_deleted_at", table_name="sessions")
    op.drop_constraint("ck_sessions_visibility", "sessions", type_="check")
    op.drop_column("sessions", "pending_confirm_author_id")
    op.drop_column("sessions", "deleted_at")
    op.drop_column("sessions", "visibility")
