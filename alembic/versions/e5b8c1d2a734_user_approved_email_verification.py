"""user approved flag for email verification

Adds users.approved. Existing accounts pre-date verification and are marked
approved so nobody is locked out. Email uniqueness is relaxed to apply only
among approved accounts: the plain unique index on user_email becomes a
regular index and the lower(user_email) unique index becomes partial.

Revision ID: e5b8c1d2a734
Revises: d4a7f0c9b215
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b8c1d2a734'
down_revision: Union[str, Sequence[str], None] = 'd4a7f0c9b215'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    # Accounts created before verification existed are trusted as-is.
    op.execute("UPDATE users SET approved = true")

    op.drop_index('ix_users_user_email', table_name='users')
    op.create_index('ix_users_user_email', 'users', ['user_email'], unique=False)

    op.execute("DROP INDEX IF EXISTS uq_users_user_email_lower")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_user_email_lower_approved "
        "ON users (lower(user_email)) WHERE approved"
    )


def downgrade() -> None:
    # Fails if unverified duplicate sign-ups exist; remove them first.
    op.execute("DROP INDEX IF EXISTS uq_users_user_email_lower_approved")
    op.execute("CREATE UNIQUE INDEX uq_users_user_email_lower ON users (lower(user_email))")
    op.drop_index('ix_users_user_email', table_name='users')
    op.create_index('ix_users_user_email', 'users', ['user_email'], unique=True)
    op.drop_column('users', 'approved')
