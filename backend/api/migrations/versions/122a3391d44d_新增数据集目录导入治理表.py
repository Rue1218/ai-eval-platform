"""新增数据集目录导入治理表

Revision ID: 122a3391d44d
Revises: e7a1c3f52b48
Create Date: 2026-08-28 16:10:05.175989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '122a3391d44d'
down_revision: Union[str, None] = 'e7a1c3f52b48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建目录治理、导入队列、staging 与不可变版本表。"""
    # 自动生成结果已审阅：历史 M2 数据集列已由 b3e71a9c42f6 创建，不能重复添加。
    op.create_table('dataset_catalog_entries',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('upstream_owner', sa.String(), nullable=False),
    sa.Column('official_project_url', sa.Text(), nullable=False),
    sa.Column('allowed_domains', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('purpose', sa.String(), nullable=False),
    sa.Column('evidence_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('submitted_by', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dataset_catalog_entries_status'), 'dataset_catalog_entries', ['status'], unique=False)
    op.create_index(op.f('ix_dataset_catalog_entries_submitted_by'), 'dataset_catalog_entries', ['submitted_by'], unique=False)
    op.create_table('dataset_catalog_releases',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('catalog_entry_id', sa.String(), nullable=False),
    sa.Column('display_version', sa.String(), nullable=False),
    sa.Column('source_revision', sa.String(), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('manifest_hash', sa.String(length=64), nullable=False),
    sa.Column('license', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('allowed_splits', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('filter_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('parser_id', sa.String(), nullable=False),
    sa.Column('parser_version', sa.String(), nullable=False),
    sa.Column('task_family', sa.String(), nullable=False),
    sa.Column('support_status', sa.String(), nullable=False),
    sa.Column('risk_labels', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('submitted_by', sa.String(), nullable=False),
    sa.Column('approved_by', sa.String(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['catalog_entry_id'], ['dataset_catalog_entries.id'], ),
    sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('catalog_entry_id', 'manifest_hash', name='uq_catalog_release_manifest')
    )
    op.create_index(op.f('ix_dataset_catalog_releases_catalog_entry_id'), 'dataset_catalog_releases', ['catalog_entry_id'], unique=False)
    op.create_index(op.f('ix_dataset_catalog_releases_manifest_hash'), 'dataset_catalog_releases', ['manifest_hash'], unique=False)
    op.create_index(op.f('ix_dataset_catalog_releases_status'), 'dataset_catalog_releases', ['status'], unique=False)
    op.create_index(op.f('ix_dataset_catalog_releases_submitted_by'), 'dataset_catalog_releases', ['submitted_by'], unique=False)
    op.create_table('dataset_catalog_reviews',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('catalog_entry_id', sa.String(), nullable=True),
    sa.Column('release_id', sa.String(), nullable=True),
    sa.Column('actor_id', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('previous_status', sa.String(), nullable=True),
    sa.Column('next_status', sa.String(), nullable=False),
    sa.Column('manifest_hash', sa.String(length=64), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['catalog_entry_id'], ['dataset_catalog_entries.id'], ),
    sa.ForeignKeyConstraint(['release_id'], ['dataset_catalog_releases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dataset_catalog_reviews_actor_id'), 'dataset_catalog_reviews', ['actor_id'], unique=False)
    op.create_index(op.f('ix_dataset_catalog_reviews_catalog_entry_id'), 'dataset_catalog_reviews', ['catalog_entry_id'], unique=False)
    op.create_index(op.f('ix_dataset_catalog_reviews_release_id'), 'dataset_catalog_reviews', ['release_id'], unique=False)
    op.create_table('dataset_imports',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('dataset_id', sa.String(), nullable=False),
    sa.Column('catalog_release_id', sa.String(), nullable=False),
    sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('manifest_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('lease_token', sa.String(length=64), nullable=True),
    sa.Column('lease_owner', sa.String(), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('staging_revision', sa.Integer(), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_by', sa.String(), nullable=False),
    sa.Column('reviewed_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['catalog_release_id'], ['dataset_catalog_releases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lease_token'),
    sa.UniqueConstraint('request_fingerprint', name='uq_dataset_import_fingerprint')
    )
    op.create_index('ix_dataset_import_queue', 'dataset_imports', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_dataset_imports_catalog_release_id'), 'dataset_imports', ['catalog_release_id'], unique=False)
    op.create_index(op.f('ix_dataset_imports_created_by'), 'dataset_imports', ['created_by'], unique=False)
    op.create_index(op.f('ix_dataset_imports_dataset_id'), 'dataset_imports', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_imports_lease_expires_at'), 'dataset_imports', ['lease_expires_at'], unique=False)
    op.create_index(op.f('ix_dataset_imports_manifest_hash'), 'dataset_imports', ['manifest_hash'], unique=False)
    op.create_index(op.f('ix_dataset_imports_status'), 'dataset_imports', ['status'], unique=False)
    op.create_table('dataset_import_attempts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('import_id', sa.String(), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('worker_id', sa.String(), nullable=True),
    sa.Column('lease_token', sa.String(length=64), nullable=False),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('error_code', sa.String(), nullable=True),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['import_id'], ['dataset_imports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('import_id', 'attempt_no', name='uq_dataset_import_attempt'),
    sa.UniqueConstraint('lease_token')
    )
    op.create_index(op.f('ix_dataset_import_attempts_import_id'), 'dataset_import_attempts', ['import_id'], unique=False)
    op.create_table('dataset_import_rows',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('import_id', sa.String(), nullable=False),
    sa.Column('row_no', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('reference', sa.Text(), nullable=False),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('row_status', sa.String(), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['import_id'], ['dataset_imports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('import_id', 'row_no', name='uq_dataset_import_row_no')
    )
    op.create_index(op.f('ix_dataset_import_rows_import_id'), 'dataset_import_rows', ['import_id'], unique=False)
    op.create_table('dataset_source_artifacts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('import_id', sa.String(), nullable=False),
    sa.Column('artifact_name', sa.String(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('media_type', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['import_id'], ['dataset_imports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dataset_source_artifacts_import_id'), 'dataset_source_artifacts', ['import_id'], unique=False)
    op.create_index(op.f('ix_dataset_source_artifacts_sha256'), 'dataset_source_artifacts', ['sha256'], unique=False)
    op.create_table('dataset_versions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('dataset_id', sa.String(), nullable=False),
    sa.Column('import_id', sa.String(), nullable=True),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('scorer_version', sa.String(), nullable=False),
    sa.Column('published_by', sa.String(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
    sa.ForeignKeyConstraint(['import_id'], ['dataset_imports.id'], ),
    sa.ForeignKeyConstraint(['published_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'version_no', name='uq_dataset_version_no')
    )
    op.create_index(op.f('ix_dataset_versions_content_sha256'), 'dataset_versions', ['content_sha256'], unique=False)
    op.create_index(op.f('ix_dataset_versions_dataset_id'), 'dataset_versions', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_versions_import_id'), 'dataset_versions', ['import_id'], unique=False)
    op.create_table('dataset_version_rows',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('dataset_version_id', sa.String(), nullable=False),
    sa.Column('source_import_row_id', sa.String(), nullable=True),
    sa.Column('row_no', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('reference', sa.Text(), nullable=False),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['source_import_row_id'], ['dataset_import_rows.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_version_id', 'row_no', name='uq_dataset_version_row_no')
    )
    op.create_index(op.f('ix_dataset_version_rows_dataset_version_id'), 'dataset_version_rows', ['dataset_version_id'], unique=False)
    op.add_column('datasets', sa.Column('status', sa.String(), server_default='draft', nullable=False))
    op.add_column('datasets', sa.Column('active_version_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_datasets_active_version_id'), 'datasets', ['active_version_id'], unique=False)
    op.create_foreign_key('fk_datasets_active_version', 'datasets', 'dataset_versions', ['active_version_id'], ['id'], use_alter=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    """删除 M3 数据集导入治理表，并恢复旧数据集容器结构。"""
    op.drop_constraint('fk_datasets_active_version', 'datasets', type_='foreignkey')
    op.drop_index(op.f('ix_datasets_active_version_id'), table_name='datasets')
    op.drop_column('datasets', 'active_version_id')
    op.drop_column('datasets', 'status')
    op.drop_index(op.f('ix_dataset_version_rows_dataset_version_id'), table_name='dataset_version_rows')
    op.drop_table('dataset_version_rows')
    op.drop_index(op.f('ix_dataset_versions_import_id'), table_name='dataset_versions')
    op.drop_index(op.f('ix_dataset_versions_dataset_id'), table_name='dataset_versions')
    op.drop_index(op.f('ix_dataset_versions_content_sha256'), table_name='dataset_versions')
    op.drop_table('dataset_versions')
    op.drop_index(op.f('ix_dataset_source_artifacts_sha256'), table_name='dataset_source_artifacts')
    op.drop_index(op.f('ix_dataset_source_artifacts_import_id'), table_name='dataset_source_artifacts')
    op.drop_table('dataset_source_artifacts')
    op.drop_index(op.f('ix_dataset_import_rows_import_id'), table_name='dataset_import_rows')
    op.drop_table('dataset_import_rows')
    op.drop_index(op.f('ix_dataset_import_attempts_import_id'), table_name='dataset_import_attempts')
    op.drop_table('dataset_import_attempts')
    op.drop_index(op.f('ix_dataset_imports_status'), table_name='dataset_imports')
    op.drop_index(op.f('ix_dataset_imports_manifest_hash'), table_name='dataset_imports')
    op.drop_index(op.f('ix_dataset_imports_lease_expires_at'), table_name='dataset_imports')
    op.drop_index(op.f('ix_dataset_imports_dataset_id'), table_name='dataset_imports')
    op.drop_index(op.f('ix_dataset_imports_created_by'), table_name='dataset_imports')
    op.drop_index(op.f('ix_dataset_imports_catalog_release_id'), table_name='dataset_imports')
    op.drop_index('ix_dataset_import_queue', table_name='dataset_imports')
    op.drop_table('dataset_imports')
    op.drop_index(op.f('ix_dataset_catalog_reviews_release_id'), table_name='dataset_catalog_reviews')
    op.drop_index(op.f('ix_dataset_catalog_reviews_catalog_entry_id'), table_name='dataset_catalog_reviews')
    op.drop_index(op.f('ix_dataset_catalog_reviews_actor_id'), table_name='dataset_catalog_reviews')
    op.drop_table('dataset_catalog_reviews')
    op.drop_index(op.f('ix_dataset_catalog_releases_submitted_by'), table_name='dataset_catalog_releases')
    op.drop_index(op.f('ix_dataset_catalog_releases_status'), table_name='dataset_catalog_releases')
    op.drop_index(op.f('ix_dataset_catalog_releases_manifest_hash'), table_name='dataset_catalog_releases')
    op.drop_index(op.f('ix_dataset_catalog_releases_catalog_entry_id'), table_name='dataset_catalog_releases')
    op.drop_table('dataset_catalog_releases')
    op.drop_index(op.f('ix_dataset_catalog_entries_submitted_by'), table_name='dataset_catalog_entries')
    op.drop_index(op.f('ix_dataset_catalog_entries_status'), table_name='dataset_catalog_entries')
    op.drop_table('dataset_catalog_entries')
    # ### end Alembic commands ###
