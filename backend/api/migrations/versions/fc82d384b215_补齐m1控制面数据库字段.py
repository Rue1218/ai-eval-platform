"""补齐 M1 控制面数据库字段。

Revision ID: fc82d384b215
Revises: 0001
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 迁移标识。
revision: str = "fc82d384b215"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """在 0001 最小骨架上安全补齐 M1 控制面实体与约束。"""
    # 自动生成的差异已审阅：以下默认值先保障已有骨架数据可回填，再移除写入默认值。
    op.create_table(
        "files",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("uploaded_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name="fk_files_uploaded_by_users"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path", name="uq_files_storage_path"),
    )
    op.create_index("ix_files_sha256", "files", ["sha256"], unique=False)
    op.create_index("ix_files_uploaded_by", "files", ["uploaded_by"], unique=False)

    op.create_table(
        "dispatch_workers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("caps", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("load_percent", sa.Float(), nullable=True),
        sa.Column("current_task_id", sa.String(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_task_id"], ["tasks.id"], name="fk_dispatch_workers_current_task"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dispatch_workers_state", "dispatch_workers", ["state"], unique=False)

    op.create_table(
        "dispatch_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_dispatch_events_task"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["dispatch_workers.id"], name="fk_dispatch_events_worker"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dispatch_events_task_id", "dispatch_events", ["task_id"], unique=False)
    op.create_index(
        "ix_dispatch_events_worker_id", "dispatch_events", ["worker_id"], unique=False
    )

    op.add_column("users", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_ip", sa.String(), nullable=True))
    op.execute("UPDATE users SET role = 'member'")
    op.execute("UPDATE users SET disabled = FALSE WHERE disabled IS NULL")
    op.alter_column("users", "disabled", existing_type=sa.Boolean(), nullable=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.alter_column("users", "must_change_password", server_default=None)
    op.alter_column("users", "auth_version", server_default=None)

    op.add_column(
        "sessions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.alter_column("sessions", "updated_at", server_default=None)

    op.add_column(
        "messages",
        sa.Column(
            "attachments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("messages", "attachments", server_default=None)

    op.add_column("ws_events", sa.Column("task_id", sa.String(), nullable=True))
    op.create_index("ix_ws_events_task_id", "ws_events", ["task_id"], unique=False)
    op.create_unique_constraint("uq_ws_events_session_event", "ws_events", ["session_id", "event_id"])
    op.create_foreign_key(
        "fk_ws_events_session", "ws_events", "sessions", ["session_id"], ["id"]
    )

    op.add_column(
        "protocol_profiles",
        sa.Column(
            "usages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("protocol_profiles", sa.Column("anthropic_version", sa.String(), nullable=True))
    op.add_column(
        "protocol_profiles",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_check_constraint(
        "ck_protocol_profiles_protocol",
        "protocol_profiles",
        "protocol IN ('openai_chat', 'openai_responses', 'anthropic_messages')",
    )
    op.alter_column("protocol_profiles", "usages", server_default=None)
    op.alter_column("protocol_profiles", "updated_at", server_default=None)

    op.add_column("settings", sa.Column("updated_by", sa.String(), nullable=True))
    op.create_foreign_key("fk_settings_updated_by", "settings", "users", ["updated_by"], ["id"])

    op.add_column("audit_logs", sa.Column("target_type", sa.String(), nullable=True))
    op.add_column("audit_logs", sa.Column("target_id", sa.String(), nullable=True))
    op.add_column("audit_logs", sa.Column("ip", sa.String(), nullable=True))
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)

    op.add_column(
        "tasks",
        sa.Column(
            "progress",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("tasks", sa.Column("claimed_by_worker_id", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tasks", sa.Column("attempt", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("tasks", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_created_by", "tasks", ["created_by"], unique=False)
    op.create_index("ix_tasks_queue", "tasks", ["status", "created_at"], unique=False)
    op.create_index(
        "uq_tasks_active_session",
        "tasks",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(
            "session_id IS NOT NULL AND status IN "
            "('queued', 'running', 'awaiting_case_confirm')"
        ),
    )
    op.create_check_constraint(
        "ck_tasks_kind", "tasks", "kind IN ('benchmark', 'rag', 'testcase', 'stress')"
    )
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('queued', 'running', 'awaiting_case_confirm', "
        "'succeeded', 'failed', 'cancelled')",
    )
    op.create_foreign_key("fk_tasks_session", "tasks", "sessions", ["session_id"], ["id"])
    op.create_foreign_key("fk_tasks_parent", "tasks", "tasks", ["parent_task_id"], ["id"])
    op.alter_column("tasks", "progress", server_default=None)
    op.alter_column("tasks", "attempt", server_default=None)

    op.add_column(
        "task_events",
        sa.Column("level", sa.String(), nullable=False, server_default="info"),
    )
    op.add_column("task_events", sa.Column("message", sa.Text(), nullable=True))
    op.create_foreign_key("fk_task_events_task", "task_events", "tasks", ["task_id"], ["id"])
    op.alter_column("task_events", "level", server_default=None)

    op.drop_index("ix_reports_task_id", table_name="reports")
    op.create_index("ix_reports_task_id", "reports", ["task_id"], unique=True)
    op.create_foreign_key("fk_reports_task", "reports", "tasks", ["task_id"], ["id"])


def downgrade() -> None:
    """按反向依赖删除 M1 追加的表、约束、索引和字段。"""
    op.drop_constraint("fk_reports_task", "reports", type_="foreignkey")
    op.drop_index("ix_reports_task_id", table_name="reports")
    op.create_index("ix_reports_task_id", "reports", ["task_id"], unique=False)

    op.drop_constraint("fk_task_events_task", "task_events", type_="foreignkey")
    op.drop_column("task_events", "message")
    op.drop_column("task_events", "level")

    op.drop_constraint("fk_tasks_parent", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_session", "tasks", type_="foreignkey")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.drop_constraint("ck_tasks_kind", "tasks", type_="check")
    op.drop_index("uq_tasks_active_session", table_name="tasks")
    op.drop_index("ix_tasks_queue", table_name="tasks")
    op.drop_index("ix_tasks_created_by", table_name="tasks")
    op.drop_column("tasks", "cancel_requested_at")
    op.drop_column("tasks", "attempt")
    op.drop_column("tasks", "claim_expires_at")
    op.drop_column("tasks", "claimed_by_worker_id")
    op.drop_column("tasks", "progress")

    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_column("audit_logs", "ip")
    op.drop_column("audit_logs", "target_id")
    op.drop_column("audit_logs", "target_type")

    op.drop_constraint("fk_settings_updated_by", "settings", type_="foreignkey")
    op.drop_column("settings", "updated_by")

    op.drop_constraint("ck_protocol_profiles_protocol", "protocol_profiles", type_="check")
    op.drop_column("protocol_profiles", "updated_at")
    op.drop_column("protocol_profiles", "anthropic_version")
    op.drop_column("protocol_profiles", "usages")

    op.drop_constraint("fk_ws_events_session", "ws_events", type_="foreignkey")
    op.drop_constraint("uq_ws_events_session_event", "ws_events", type_="unique")
    op.drop_index("ix_ws_events_task_id", table_name="ws_events")
    op.drop_column("ws_events", "task_id")

    op.drop_column("messages", "attachments")
    op.drop_column("sessions", "updated_at")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "auth_version")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "email")
    op.drop_column("users", "display_name")

    op.drop_index("ix_dispatch_events_worker_id", table_name="dispatch_events")
    op.drop_index("ix_dispatch_events_task_id", table_name="dispatch_events")
    op.drop_table("dispatch_events")
    op.drop_index("ix_dispatch_workers_state", table_name="dispatch_workers")
    op.drop_table("dispatch_workers")
    op.drop_index("ix_files_uploaded_by", table_name="files")
    op.drop_index("ix_files_sha256", table_name="files")
    op.drop_table("files")
