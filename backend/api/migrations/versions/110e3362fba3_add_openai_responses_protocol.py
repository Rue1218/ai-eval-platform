"""协议档增加 OpenAI Responses 格式。

Revision ID: 110e3362fba3
Revises: f70e5a53bd54
Create Date: 2026-09-17 10:23:33.605663

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '110e3362fba3'
down_revision: Union[str, None] = 'f70e5a53bd54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """扩展约束；Alembic autogenerate 不检测 CHECK 文本，生成后显式补齐。"""
    op.drop_constraint('ck_protocol_profiles_protocol', 'protocol_profiles', type_='check')
    op.create_check_constraint(
        'ck_protocol_profiles_protocol', 'protocol_profiles',
        "protocol IN ('openai_chat', 'openai_responses', 'anthropic_messages')",
    )


def downgrade() -> None:
    """已有新协议档时拒绝回退，禁止把 Responses 静默改成 Chat。"""
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM protocol_profiles WHERE protocol = 'openai_responses') THEN
                RAISE EXCEPTION 'Remove Responses profiles before downgrade';
            END IF;
        END $$;
    """))
    op.drop_constraint('ck_protocol_profiles_protocol', 'protocol_profiles', type_='check')
    op.create_check_constraint(
        'ck_protocol_profiles_protocol', 'protocol_profiles',
        "protocol IN ('openai_chat', 'anthropic_messages')",
    )
