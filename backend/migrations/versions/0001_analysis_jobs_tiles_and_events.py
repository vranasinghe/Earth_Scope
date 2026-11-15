"""analysis jobs, tiles and events

Revision ID: 0001
Revises: 
Create Date: 2026-11-15 00:24:55.962671
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Generated with alembic --autogenerate from app/jobs/models.py, reviewed by hand.
    op.create_table('analysis_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_hash', sa.String(length=64), nullable=False),
    sa.Column('client_ip_hash', sa.String(length=64), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('job_type', sa.String(length=32), nullable=False),
    sa.Column('area_kind', sa.String(length=16), nullable=False),
    sa.Column('area_name', sa.String(length=120), nullable=False),
    sa.Column('iso3', sa.String(length=3), nullable=True),
    sa.Column('geometry_id', sa.String(length=64), nullable=False),
    sa.Column('boundary_source', sa.String(length=64), nullable=True),
    sa.Column('boundary_version', sa.String(length=128), nullable=True),
    sa.Column('variable_id', sa.String(length=64), nullable=False),
    sa.Column('parameter', sa.String(length=32), nullable=False),
    sa.Column('community', sa.String(length=8), nullable=False),
    sa.Column('start_year', sa.Integer(), nullable=False),
    sa.Column('end_year', sa.Integer(), nullable=False),
    sa.Column('coverage_threshold', sa.Float(), nullable=False),
    sa.Column('method', sa.String(length=40), nullable=False),
    sa.Column('correction', sa.String(length=16), nullable=False),
    sa.Column('alpha', sa.Float(), nullable=False),
    sa.Column('data_mode', sa.String(length=8), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('config_hash', sa.String(length=64), nullable=False),
    sa.Column('active_dedupe_key', sa.String(length=64), nullable=True),
    sa.Column('tier', sa.String(length=16), nullable=False),
    sa.Column('preflight', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('input_ref', sa.String(length=255), nullable=False),
    sa.Column('input_sha256', sa.String(length=64), nullable=False),
    sa.Column('software_version', sa.String(length=64), nullable=False),
    sa.Column('dataset_version', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('stage', sa.String(length=40), nullable=False),
    sa.Column('activity', sa.String(length=300), nullable=True),
    sa.Column('tiles_total', sa.Integer(), nullable=False),
    sa.Column('tiles_completed', sa.Integer(), nullable=False),
    sa.Column('tiles_retrying', sa.Integer(), nullable=False),
    sa.Column('tiles_failed', sa.Integer(), nullable=False),
    sa.Column('cells_total', sa.Integer(), nullable=False),
    sa.Column('cells_processed', sa.Integer(), nullable=False),
    sa.Column('progress_pct', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('auto_attempts', sa.Integer(), nullable=False),
    sa.Column('manual_retries', sa.Integer(), nullable=False),
    sa.Column('lease_owner', sa.String(length=128), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rq_job_id', sa.String(length=80), nullable=True),
    sa.Column('error_code', sa.String(length=48), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('error_retryable', sa.Boolean(), nullable=True),
    sa.Column('checkpoints', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('metrics', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('result_ref', sa.String(length=255), nullable=True),
    sa.Column('result_sha256', sa.String(length=64), nullable=True),
    sa.Column('result_bytes', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_hash', 'active_dedupe_key', name='uq_jobs_owner_active_config'),
    sa.UniqueConstraint('owner_hash', 'idempotency_key', name='uq_jobs_owner_idempotency_key')
    )
    with op.batch_alter_table('analysis_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_analysis_jobs_client_ip_hash'), ['client_ip_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_jobs_config_hash'), ['config_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_jobs_lease_expires_at'), ['lease_expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_jobs_owner_hash'), ['owner_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_jobs_status'), ['status'], unique=False)
        batch_op.create_index('ix_jobs_owner_created', ['owner_hash', 'created_at'], unique=False)
        batch_op.create_index('ix_jobs_status_next_attempt', ['status', 'next_attempt_at'], unique=False)

    op.create_table('job_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_events_job_id'), ['job_id'], unique=False)

    op.create_table('job_tiles',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('tile_key', sa.String(length=16), nullable=False),
    sa.Column('lat_min', sa.Float(), nullable=False),
    sa.Column('lat_max', sa.Float(), nullable=False),
    sa.Column('lon_min', sa.Float(), nullable=False),
    sa.Column('lon_max', sa.Float(), nullable=False),
    sa.Column('n_needed', sa.Integer(), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_error_code', sa.String(length=48), nullable=True),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('blob_sha256', sa.String(length=64), nullable=True),
    sa.Column('blob_bytes', sa.Integer(), nullable=True),
    sa.Column('request_url', sa.Text(), nullable=True),
    sa.Column('retrieved_at', sa.String(length=40), nullable=True),
    sa.Column('from_cache', sa.Boolean(), nullable=False),
    sa.Column('n_features', sa.Integer(), nullable=True),
    sa.Column('validation', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'tile_key', name='uq_job_tiles_job_tile')
    )
    with op.batch_alter_table('job_tiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_tiles_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_tiles_request_hash'), ['request_hash'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # Generated with alembic --autogenerate from app/jobs/models.py, reviewed by hand.
    with op.batch_alter_table('job_tiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_tiles_request_hash'))
        batch_op.drop_index(batch_op.f('ix_job_tiles_job_id'))

    op.drop_table('job_tiles')
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_events_job_id'))

    op.drop_table('job_events')
    with op.batch_alter_table('analysis_jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_jobs_status_next_attempt')
        batch_op.drop_index('ix_jobs_owner_created')
        batch_op.drop_index(batch_op.f('ix_analysis_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_analysis_jobs_owner_hash'))
        batch_op.drop_index(batch_op.f('ix_analysis_jobs_lease_expires_at'))
        batch_op.drop_index(batch_op.f('ix_analysis_jobs_config_hash'))
        batch_op.drop_index(batch_op.f('ix_analysis_jobs_client_ip_hash'))

    op.drop_table('analysis_jobs')
    # ### end Alembic commands ###
