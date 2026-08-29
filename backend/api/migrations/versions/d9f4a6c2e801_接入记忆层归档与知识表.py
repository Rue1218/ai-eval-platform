"""接入记忆层归档与 pgvector 知识表。

Revision ID: d9f4a6c2e801
Revises: b7e4a1c90825
Create Date: 2026-08-22 13:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic 自动生成需连接本地 PostgreSQL；当前开发机无可用实例，已执行生成尝试后
# 以同一 metadata 差异人工复核本可逆脚本。部署仍由 entrypoint 的 alembic upgrade head 执行。
revision: str = "d9f4a6c2e801"
down_revision: str | None = "b7e4a1c90825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class PgVectorType(sa.types.UserDefinedType):
    """迁移内 pgvector 类型定义，避免迁移依赖应用模块导入路径。"""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        """知识向量固定为 1536 维，与共享模型定义一致。"""
        return "vector(1536)"


def upgrade() -> None:
    """为消息补 provenance，并创建同库的 pgvector 知识表与 ACL 索引。"""
    # pgvector 镜像首次初始化会创建扩展；此处兼容已有数据卷的升级路径或未安装扩展的环境。
    bind = op.get_bind()
    has_vector = False
    try:
        res = bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")).scalar()
        if res:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
            has_vector = True
    except Exception:
        has_vector = False

    op.add_column("messages", sa.Column("source_id", sa.String(), nullable=True))
    op.add_column(
        "messages", sa.Column("source_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("messages", sa.Column("origin_trace_id", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("origin_span_id", sa.String(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("memory_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # 存量消息保留其原有审计语义，同时获得可撤权的稳定来源 ID。
    op.execute("UPDATE messages SET source_id = 'message:' || id WHERE source_id IS NULL")
    op.alter_column("messages", "source_id", existing_type=sa.String(), nullable=False)
    op.alter_column("messages", "source_version", server_default=None)
    op.alter_column("messages", "memory_revoked", server_default=None)
    op.create_index("ix_messages_source_id", "messages", ["source_id"], unique=False)
    op.create_index("ix_messages_origin_trace_id", "messages", ["origin_trace_id"], unique=False)

    op.create_table(
        "memory_knowledge",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", PgVectorType() if has_vector else sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("acl", sa.String(), nullable=False),
        sa.Column("acl_user_ids", postgresql.JSONB(), nullable=False),
        sa.Column("origin_trace_id", sa.String(), nullable=True),
        sa.Column("origin_span_id", sa.String(), nullable=True),
        sa.Column("memory_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("memory_knowledge", "memory_revoked", server_default=None)
    op.create_index("ix_memory_knowledge_tenant_id", "memory_knowledge", ["tenant_id"], unique=False)
    op.create_index("ix_memory_knowledge_source_id", "memory_knowledge", ["source_id"], unique=False)
    op.create_index(
        "ix_memory_knowledge_tenant_source",
        "memory_knowledge",
        ["tenant_id", "source_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_knowledge_revoked", "memory_knowledge", ["memory_revoked"], unique=False
    )
    op.create_index(
        "ix_memory_knowledge_origin_trace_id",
        "memory_knowledge",
        ["origin_trace_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚记忆业务表和消息 provenance 列；不删除其他模块可能共用的 vector 扩展。"""
    op.drop_index("ix_memory_knowledge_origin_trace_id", table_name="memory_knowledge")
    op.drop_index("ix_memory_knowledge_revoked", table_name="memory_knowledge")
    op.drop_index("ix_memory_knowledge_tenant_source", table_name="memory_knowledge")
    op.drop_index("ix_memory_knowledge_source_id", table_name="memory_knowledge")
    op.drop_index("ix_memory_knowledge_tenant_id", table_name="memory_knowledge")
    op.drop_table("memory_knowledge")

    op.drop_index("ix_messages_origin_trace_id", table_name="messages")
    op.drop_index("ix_messages_source_id", table_name="messages")
    op.drop_column("messages", "memory_revoked")
    op.drop_column("messages", "origin_span_id")
    op.drop_column("messages", "origin_trace_id")
    op.drop_column("messages", "source_version")
    op.drop_column("messages", "source_id")
