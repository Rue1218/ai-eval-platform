"""会话权限档位列（三档权限等级：tier1 请求批准 / tier2 帮我批准 / tier3 完全访问）。

``sessions`` 增 ``permission_tier``（可空）：非空覆盖全局
``settings.permission_tier_default``，空则继承全局默认。运行期由
``loop_wiring.context_factory`` 解析进 ``ToolExecutionContext``，不进入模型上下文。

Revision ID: f3a91b2c7d40
Revises: 01b89a06eb4b
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a91b2c7d40"
down_revision: str | None = "01b89a06eb4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为会话增加权限档位列（可空，空=继承全局默认）。"""
    op.add_column("sessions", sa.Column("permission_tier", sa.String(), nullable=True))


def downgrade() -> None:
    """回滚会话权限档位列。"""
    op.drop_column("sessions", "permission_tier")
