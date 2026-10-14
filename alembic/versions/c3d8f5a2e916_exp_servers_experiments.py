"""add exp_servers / exp_experiments for multi-server experiment registry

Revision ID: c3d8f5a2e916
Revises: b9e4f1a6d2c7
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d8f5a2e916'
down_revision = 'b9e4f1a6d2c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'exp_servers',
        sa.Column('server_id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('kind', sa.String(16), nullable=False, server_default='ssh'),
        sa.Column('host', sa.String(255), nullable=True),
        sa.Column('ssh_port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('ssh_user', sa.String(255), nullable=True),
        sa.Column('auth_type', sa.String(16), nullable=False, server_default='key'),
        sa.Column('ssh_key_path', sa.String(1024), nullable=True),
        sa.Column('ssh_password', sa.String(255), nullable=True),
        sa.Column('ais_root', sa.String(1024), nullable=False, server_default='~/ais'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        'exp_experiments',
        sa.Column('exp_name', sa.String(255), primary_key=True),
        sa.Column('server_id', sa.Integer(),
                  sa.ForeignKey('exp_servers.server_id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('job_id', sa.Integer(),
                  sa.ForeignKey('jobs.job_id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('remote_mtime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('exp_experiments')
    op.drop_table('exp_servers')