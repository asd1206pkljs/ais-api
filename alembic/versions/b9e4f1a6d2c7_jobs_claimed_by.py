"""add jobs.claimed_by for multi-server atomic job claim

Revision ID: b9e4f1a6d2c7
Revises: a7d9e1c3f0b8
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'b9e4f1a6d2c7'
down_revision = 'a7d9e1c3f0b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'jobs',
        sa.Column('claimed_by', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('jobs', 'claimed_by')