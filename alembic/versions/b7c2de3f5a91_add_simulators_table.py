"""add simulators table

Revision ID: b7c2de3f5a91
Revises: a3f1bc2d4e56
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c2de3f5a91'
down_revision: Union[str, Sequence[str], None] = 'a3f1bc2d4e56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'simulators',
        sa.Column('simulator_id', sa.UUID(), nullable=False),
        sa.Column('simulator_name', sa.String(length=255), nullable=False),
        sa.Column('equipment_id', sa.UUID(), nullable=False),
        sa.Column('simulator_path', sa.String(length=1024), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('save_status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['equipment_id'], ['equipment.equipment_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('simulator_id'),
    )
    op.create_index('ix_simulators_equipment_id', 'simulators', ['equipment_id'])
    op.create_index('ix_simulators_owner_id', 'simulators', ['owner_id'])


def downgrade() -> None:
    op.drop_index('ix_simulators_owner_id', table_name='simulators')
    op.drop_index('ix_simulators_equipment_id', table_name='simulators')
    op.drop_table('simulators')
