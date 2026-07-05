"""jobs: int PK + simulator_id FK, drop job_path, update status enum

Revision ID: f6a9b2d1c8e4
Revises: e3b1c4d9f207
Create Date: 2026-04-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'f6a9b2d1c8e4'
down_revision = 'e3b1c4d9f207'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop and recreate jobs table:
    # - job_id changes from UUID to Integer autoincrement
    # - drop job_path (internal filesystem path should not be persisted)
    # - add simulator_id FK (NOT NULL, CASCADE on simulator delete)
    # - job_status values now: pending / training / complete
    op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
    op.drop_table('jobs')

    op.create_table(
        'jobs',
        sa.Column('job_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('simulator_id', UUID(as_uuid=True), nullable=False),
        sa.Column('job_name', sa.String(length=255), nullable=False),
        sa.Column('job_status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['simulator_id'], ['simulators.simulator_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id'),
    )
    op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'])
    op.create_index(op.f('ix_jobs_simulator_id'), 'jobs', ['simulator_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_jobs_simulator_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
    op.drop_table('jobs')

    op.create_table(
        'jobs',
        sa.Column('job_id', UUID(), nullable=False),
        sa.Column('user_id', UUID(), nullable=False),
        sa.Column('job_name', sa.String(length=255), nullable=False),
        sa.Column('job_path', sa.String(length=1024), nullable=False),
        sa.Column('job_status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id'),
    )
    op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'])
