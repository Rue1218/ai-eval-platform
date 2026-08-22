"""新增 pgvector 知识记忆表。

Revision ID: d6f2a91be430
Revises: c650ba766b96
Create Date: 2026-08-22 16:20:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType


class PgVector(UserDefinedType):
    """迁移内最小 pgvector 类型声明，避免迁移依赖运行时适配器模块。"""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        """生成 pgvector 扩展提供的未定维 vector 列。"""
        return "vector"


# revision identifiers, used by Alembic.
revision: str = "d6f2a91be430"
down_revision: Union[str, None] = "c650ba766b96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """启用同库 pgvector 并创建带 ACL、来源、撤权标记的知识记忆表。"""
    # 扩展已存在时保持幂等；本迁移不假设初始化卷脚本曾运行。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "memory_knowledge",
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("allowed_user_ids", JSONB(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", PgVector(), nullable=False),
        sa.Column("acl", sa.String(), nullable=False),
        sa.Column("origin_trace_id", sa.String(), nullable=True),
        sa.Column("origin_span_id", sa.String(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column(
            "memory_forgotten",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_memory_knowledge_version"),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint("source_id", "version", name="uq_memory_knowledge_source_version"),
    )
    op.create_index(
        "ix_memory_knowledge_origin_trace_id",
        "memory_knowledge",
        ["origin_trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_knowledge_scope_source",
        "memory_knowledge",
        ["tenant_id", "source_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_knowledge_recall_scope",
        "memory_knowledge",
        ["tenant_id", "memory_forgotten"],
        unique=False,
    )


def downgrade() -> None:
    """回滚知识记忆表；vector 扩展可能被其他表使用，不能盲目删除。"""
    op.drop_index("ix_memory_knowledge_recall_scope", table_name="memory_knowledge")
    op.drop_index("ix_memory_knowledge_scope_source", table_name="memory_knowledge")
    op.drop_index("ix_memory_knowledge_origin_trace_id", table_name="memory_knowledge")
    op.drop_table("memory_knowledge")
