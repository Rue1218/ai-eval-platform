"""删除 Responses 协议

Revision ID: 01b89a06eb4b
Revises: 8f9a2c4d6e01
Create Date: 2026-09-09 15:16:43.648407

"""
from typing import Sequence, Union

from alembic import context, op


# revision identifiers, used by Alembic.
revision: str = '01b89a06eb4b'
down_revision: Union[str, None] = '8f9a2c4d6e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """移除 Responses 档、其环境凭据和指向它的默认 Agent 配置。"""
    if not context.is_offline_mode():
        connection = op.get_bind()
        profile_ids = connection.exec_driver_sql(
            "SELECT id FROM protocol_profiles WHERE protocol = 'openai_responses'"
        ).scalars().all()

        # 协议档的主模型、Embedding、Reranker 密钥保存在受控环境文件；与 REST 删除
        # 操作保持一致，迁移删除档位时一并清理，不能留下可被后续 ID 重用的密钥。
        from app.profile_env import remove_profile_env

        for profile_id in profile_ids:
            remove_profile_env(str(profile_id))

    # Setting.value 是 JSONB 标量，#>> '{}' 将其取为字符串后再与即将删除的 ID 比较。
    op.execute(
        """
        DELETE FROM settings
        WHERE key = 'agent_profile_id'
          AND value #>> '{}' IN (
              SELECT id FROM protocol_profiles WHERE protocol = 'openai_responses'
          )
        """
    )
    op.execute("DELETE FROM protocol_profiles WHERE protocol = 'openai_responses'")
    op.drop_constraint("ck_protocol_profiles_protocol", "protocol_profiles", type_="check")
    op.create_check_constraint(
        "ck_protocol_profiles_protocol",
        "protocol_profiles",
        "protocol IN ('openai_chat', 'anthropic_messages')",
    )


def downgrade() -> None:
    """只恢复旧约束；被显式删除的协议档和密钥不可逆恢复。"""
    op.drop_constraint("ck_protocol_profiles_protocol", "protocol_profiles", type_="check")
    op.create_check_constraint(
        "ck_protocol_profiles_protocol",
        "protocol_profiles",
        "protocol IN ('openai_chat', 'openai_responses', 'anthropic_messages')",
    )
