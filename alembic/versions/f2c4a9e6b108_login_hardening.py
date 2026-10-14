"""login hardening: token versions, revocation denylist, lockout counters

Revision ID: f2c4a9e6b108
Revises: e5b8c1d2a734
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c4a9e6b108'
down_revision: Union[str, Sequence[str], None] = 'e5b8c1d2a734'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bumped on password change/reset so every previously issued token dies.
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.create_table(
        'login_attempts',
        sa.Column('email', sa.String(length=255), primary_key=True),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'revoked_tokens',
        sa.Column('jti', sa.String(length=64), primary_key=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'revoked_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text('now()'),
        ),
    )
    op.create_index('ix_revoked_tokens_expires_at', 'revoked_tokens', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_revoked_tokens_expires_at', table_name='revoked_tokens')
    op.drop_table('revoked_tokens')
    op.drop_table('login_attempts')
    op.drop_column('users', 'token_version')
