"""case-insensitive user email

Lowercase any existing mixed-case emails and add a functional unique index on
lower(user_email) so that addresses differing only in case can no longer be
registered as separate accounts.

Revision ID: d4a7f0c9b215
Revises: c3d8f5a2e916
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4a7f0c9b215'
down_revision: Union[str, Sequence[str], None] = 'c3d8f5a2e916'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Normalize existing data first. Any case-insensitive duplicates must
    # already be resolved, otherwise the unique index creation below fails.
    op.execute(
        "UPDATE users SET user_email = lower(user_email) "
        "WHERE user_email <> lower(user_email)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_users_user_email_lower ON users (lower(user_email))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_user_email_lower")
