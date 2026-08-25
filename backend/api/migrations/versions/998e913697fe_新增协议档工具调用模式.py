"""新增协议档工具调用模式

Revision ID: 998e913697fe
Revises: a2b4c6d8e0f2
Create Date: 2026-08-25 12:31:51.407639

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "998e913697fe"
down_revision: str | None = "a2b4c6d8e0f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增协议档原生 ToolCall 能力开关，已有档案默认兼容模式。"""
    # 由 Alembic 自动检测到新增列；临时数据库缺少后续迁移导致的 created_at
    # 差异不属于本次 schema 变更，已在审阅时剔除。
    op.add_column(
        "protocol_profiles",
        sa.Column("tool_call_mode", sa.String(), server_default="legacy", nullable=False),
    )


def downgrade() -> None:
    """回滚协议档工具调用模式字段。"""
    op.drop_column("protocol_profiles", "tool_call_mode")
