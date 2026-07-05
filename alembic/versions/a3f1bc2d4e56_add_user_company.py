"""add user_company

Revision ID: a3f1bc2d4e56
Revises: e12aaed8db60
Create Date: 2026-04-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1bc2d4e56'
down_revision: Union[str, Sequence[str], None] = 'e12aaed8db60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('user_company', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'user_company')
