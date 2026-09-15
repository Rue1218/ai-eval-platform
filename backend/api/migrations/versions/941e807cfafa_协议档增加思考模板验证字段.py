"""协议档增加思考模板验证字段。

Revision ID: 941e807cfafa
Revises: f3a91b2c7d40
Create Date: 2026-09-15 09:29:21.107542
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic 修订链标识，必须保持由 autogenerate 生成的父节点。
revision: str = "941e807cfafa"
down_revision: Union[str, None] = "f3a91b2c7d40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """保存模板绑定、非敏感探测结果和配置修订号，不改写历史协议档。"""
    op.add_column("protocol_profiles", sa.Column("reasoning_template_id", sa.String(), nullable=True))
    op.add_column("protocol_profiles", sa.Column("reasoning_probe", postgresql.JSONB(), nullable=True))
    op.add_column(
        "protocol_profiles",
        sa.Column("reasoning_config_version", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    """回滚仅移除本修订新增的思考模板元数据。"""
    op.drop_column("protocol_profiles", "reasoning_config_version")
    op.drop_column("protocol_profiles", "reasoning_probe")
    op.drop_column("protocol_profiles", "reasoning_template_id")
