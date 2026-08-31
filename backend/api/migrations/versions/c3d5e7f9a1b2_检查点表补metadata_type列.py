"""检查点表补 metadata_type 列（PgCheckpointer get_tuple/list 读回必需）。

历史 bug：a1f3c5e7b9d1 建表时漏了 metadata 的序列化类型列，put 只存
metadata blob（dumps_typed 的类型标签被丢弃），get_tuple/list 却按
``row.metadata_type`` 读取 → 一旦启用 postgres 引擎，读取已有检查点必炸
（该类从未在真实环境启用过，故未暴露）。

Revision ID: c3d5e7f9a1b2
Revises: 122a3391d44d
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d5e7f9a1b2"
down_revision: Union[str, None] = "122a3391d44d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """补列并回填：现存行的 metadata 均由 JsonPlusSerializer 写入（msgpack）。"""
    op.add_column(
        "harness_checkpoints",
        sa.Column("metadata_type", sa.Text(), nullable=False, server_default="msgpack"),
    )


def downgrade() -> None:
    """移除 metadata_type 列。"""
    op.drop_column("harness_checkpoints", "metadata_type")
