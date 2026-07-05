"""add equipment save_status, owner in viewers/editors

Revision ID: c4e8f2a91d03
Revises: b7c2de3f5a91
Create Date: 2026-04-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8f2a91d03'
down_revision = 'b7c2de3f5a91'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'equipment',
        sa.Column('save_status', sa.String(32), nullable=False, server_default='saved_temporarily'),
    )


def downgrade() -> None:
    op.drop_column('equipment', 'save_status')
