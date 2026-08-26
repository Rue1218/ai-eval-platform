"""协议档 tool_call_mode 默认值 legacy → native。

Revision ID: a9c41b7e2d10
Revises: 998e913697fe
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Alembic 迁移标识。
revision: str = "a9c41b7e2d10"
down_revision: Union[str, None] = "998e913697fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建协议档默认走原生 ToolCall;存量行保持原值不回填。

    legacy ReAct JSON 协议对模型指令遵循要求高(实测 DeepSeek 官方输出空
    工具名),native function calling 是更普适的默认;不支持工具调用的
    模型仍可显式切回 legacy。
    """
    op.alter_column(
        "protocol_profiles",
        "tool_call_mode",
        existing_type=sa.String(),
        server_default="native",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "protocol_profiles",
        "tool_call_mode",
        existing_type=sa.String(),
        server_default="legacy",
        existing_nullable=False,
    )
