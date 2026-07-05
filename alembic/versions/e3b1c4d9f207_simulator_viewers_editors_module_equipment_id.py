"""simulator: add viewers/editors; module: add equipment_id; fix simulator FK

Revision ID: e3b1c4d9f207
Revises: d5f3a7c2b891
Branch Labels: None
Depends on: None

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'e3b1c4d9f207'
down_revision = 'd5f3a7c2b891'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Fix simulators.equipment_id FK: CASCADE → SET NULL
    op.drop_constraint('simulators_equipment_id_fkey', 'simulators', type_='foreignkey')
    op.create_foreign_key(
        'simulators_equipment_id_fkey',
        'simulators', 'equipment',
        ['equipment_id'], ['equipment_id'],
        ondelete='SET NULL',
    )

    # 2. Add viewers and editors to simulators
    op.add_column('simulators', sa.Column('viewers', JSONB, nullable=False, server_default='[]'))
    op.add_column('simulators', sa.Column('editors', JSONB, nullable=False, server_default='[]'))

    # 3. Backfill existing simulators: add owner_id to viewers/editors
    op.execute("""
        UPDATE simulators
        SET
            viewers = CASE
                WHEN owner_id::text = ANY(SELECT jsonb_array_elements_text(viewers))
                THEN viewers
                ELSE viewers || jsonb_build_array(owner_id::text)
            END,
            editors = CASE
                WHEN owner_id::text = ANY(SELECT jsonb_array_elements_text(editors))
                THEN editors
                ELSE editors || jsonb_build_array(owner_id::text)
            END
    """)

    # 4. Add equipment_id to modules
    op.add_column(
        'modules',
        sa.Column('equipment_id', UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'modules_equipment_id_fkey',
        'modules', 'equipment',
        ['equipment_id'], ['equipment_id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_modules_equipment_id', 'modules', ['equipment_id'])


def downgrade() -> None:
    op.drop_index('ix_modules_equipment_id', table_name='modules')
    op.drop_constraint('modules_equipment_id_fkey', 'modules', type_='foreignkey')
    op.drop_column('modules', 'equipment_id')

    op.drop_column('simulators', 'editors')
    op.drop_column('simulators', 'viewers')

    op.drop_constraint('simulators_equipment_id_fkey', 'simulators', type_='foreignkey')
    op.create_foreign_key(
        'simulators_equipment_id_fkey',
        'simulators', 'equipment',
        ['equipment_id'], ['equipment_id'],
        ondelete='CASCADE',
    )
