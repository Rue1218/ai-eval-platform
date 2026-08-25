"""知识库、文档与黄金问答表。

Revision ID: c3a7e9b1d5f2
Revises: a2b4c6d8e0f2
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 迁移标识。
revision: str = "c3a7e9b1d5f2"
down_revision: Union[str, None] = "a2b4c6d8e0f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增知识库域四表：知识库 / 文档 / 黄金 QA 集 / 黄金 QA 行。"""
    # 知识库资产表：kind 区分 LightRAG 原生库与外部 RAG 服务。
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="lightrag"),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("is_core", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_knowledge_bases_created_by"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("knowledge_bases", "kind", server_default=None)
    op.alter_column("knowledge_bases", "is_core", server_default=None)
    op.alter_column("knowledge_bases", "created_at", server_default=None)
    op.alter_column("knowledge_bases", "updated_at", server_default=None)

    # 知识库文档表：文本正文用于切块预览与本地检索兜底。
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kb_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mime", sa.String(), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="indexed"),
        sa.Column("storage_path", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_kb_documents_created_by"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], name="fk_kb_documents_kb"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_documents_kb_id", "kb_documents", ["kb_id"], unique=False)
    op.alter_column("kb_documents", "size", server_default=None)
    op.alter_column("kb_documents", "mime", server_default=None)
    op.alter_column("kb_documents", "text", server_default=None)
    op.alter_column("kb_documents", "status", server_default=None)
    op.alter_column("kb_documents", "created_at", server_default=None)

    # 黄金 QA 集元信息表：同名覆盖上传 version 递增。
    op.create_table(
        "gold_qas",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kb_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_gold_qas_created_by"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], name="fk_gold_qas_kb"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gold_qas_kb_id", "gold_qas", ["kb_id"], unique=False)
    op.alter_column("gold_qas", "version", server_default=None)
    op.alter_column("gold_qas", "row_count", server_default=None)
    op.alter_column("gold_qas", "created_at", server_default=None)
    op.alter_column("gold_qas", "updated_at", server_default=None)

    # 黄金 QA 行表：question/reference 快照 + 期望命中文档 ID 数组。
    op.create_table(
        "gold_qa_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("gold_qa_id", sa.String(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("reference", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "expected_doc_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["gold_qa_id"], ["gold_qas.id"], name="fk_gold_qa_items_qa"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gold_qa_id", "row_no", name="uq_gold_qa_items_qa_row_no"),
    )
    op.create_index(
        "ix_gold_qa_items_gold_qa_id", "gold_qa_items", ["gold_qa_id"], unique=False
    )
    op.alter_column("gold_qa_items", "question", server_default=None)
    op.alter_column("gold_qa_items", "reference", server_default=None)
    op.alter_column("gold_qa_items", "expected_doc_ids", server_default=None)
    op.alter_column("gold_qa_items", "created_at", server_default=None)


def downgrade() -> None:
    """按反向依赖删除知识库域四表。"""
    op.drop_index("ix_gold_qa_items_gold_qa_id", table_name="gold_qa_items")
    op.drop_table("gold_qa_items")

    op.drop_index("ix_gold_qas_kb_id", table_name="gold_qas")
    op.drop_table("gold_qas")

    op.drop_index("ix_kb_documents_kb_id", table_name="kb_documents")
    op.drop_table("kb_documents")

    op.drop_table("knowledge_bases")
