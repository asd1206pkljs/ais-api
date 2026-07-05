"""simulator: nullable equipment_id, saved_temporarily status

Revision ID: d5f3a7c2b891
Revises: c4e8f2a91d03
Create Date: 2026-04-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'd5f3a7c2b891'
down_revision = 'c4e8f2a91d03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # equipment_id nullable
    op.alter_column('simulators', 'equipment_id', nullable=True)
    # rename 'temporary' -> 'saved_temporarily'
    op.execute("UPDATE simulators SET save_status = 'saved_temporarily' WHERE save_status = 'temporary'")
    op.alter_column('simulators', 'save_status',
                    existing_type=sa.String(50),
                    server_default='saved_temporarily')


def downgrade() -> None:
    op.execute("UPDATE simulators SET save_status = 'temporary' WHERE save_status = 'saved_temporarily'")
    op.alter_column('simulators', 'equipment_id', nullable=False)
