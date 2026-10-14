"""multi-user security: roles, account status, consents, groups, resource
shares, append-only audit log, user requests, recipe/module ownership

Revision ID: a7c3e1d9f204
Revises: f2c4a9e6b108
Create Date: 2026-10-14 00:00:00.000000

Data moves performed here:
- users.status = 'active' for every verified account (new sign-ups start as
  pending_approval); users.role = 'admin' for ADMIN_EMAILS from the environment
- JSONB viewers/editors lists on equipment/simulators/jobs become rows in
  resource_shares ("*" → public); the JSONB columns are dropped
- modules.owner_id is copied from the equipment they are attached to
  (recipes are linked by `python -m app.tasks.migrate_ownership`, which has
  to read the equipment config files)
"""
import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.database_ddl import AUDIT_IMMUTABLE_DROP_STATEMENTS, AUDIT_IMMUTABLE_STATEMENTS

# revision identifiers, used by Alembic.
revision: str = 'a7c3e1d9f204'
down_revision: Union[str, Sequence[str], None] = 'f2c4a9e6b108'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UUID = sa.dialects.postgresql.UUID(as_uuid=True)
_JSONB = sa.dialects.postgresql.JSONB

# (table, pk column, owner column, resource_type, has editors column)
_SHARE_SOURCES = (
    ("equipment", "equipment_id", "owner_id", "equipment", True),
    ("simulators", "simulator_id", "owner_id", "simulator", True),
    ("jobs", "job_id", "user_id", "job", False),
)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _create_tables() -> None:
    op.create_table(
        'consent_records',
        sa.Column('consent_id', _UUID, primary_key=True),
        sa.Column('user_id', _UUID, sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('document', sa.String(32), nullable=False),
        sa.Column('version', sa.String(64), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('ip_address', sa.String(64), nullable=True),
        sa.Column('user_agent', sa.String(512), nullable=True),
    )
    op.create_index('ix_consent_records_user_id', 'consent_records', ['user_id'])

    op.create_table(
        'groups',
        sa.Column('group_id', _UUID, primary_key=True),
        sa.Column('group_name', sa.String(255), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('created_by', _UUID, sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_table(
        'group_members',
        sa.Column('group_id', _UUID, sa.ForeignKey('groups.group_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', _UUID, sa.ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role', sa.String(32), nullable=False, server_default=sa.text("'member'")),
        sa.Column('added_by', _UUID, sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_group_members_user_id', 'group_members', ['user_id'])

    op.create_table(
        'resource_shares',
        sa.Column('share_id', _UUID, primary_key=True),
        sa.Column('resource_type', sa.String(32), nullable=False),
        sa.Column('resource_id', sa.String(64), nullable=False),
        sa.Column('principal_type', sa.String(16), nullable=False),
        sa.Column('principal_id', sa.String(64), nullable=False),
        sa.Column('permission', sa.String(16), nullable=False),
        sa.Column('granted_by', _UUID, sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('resource_type', 'resource_id', 'principal_type', 'principal_id',
                            name='uq_resource_shares_principal'),
    )
    op.create_index('ix_resource_shares_resource', 'resource_shares', ['resource_type', 'resource_id'])
    op.create_index('ix_resource_shares_principal', 'resource_shares', ['principal_type', 'principal_id'])

    op.create_table(
        'audit_logs',
        sa.Column('log_id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('actor_id', _UUID, nullable=True),
        sa.Column('actor_email', sa.String(255), nullable=True),
        sa.Column('actor_type', sa.String(16), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False, server_default=sa.text("'success'")),
        sa.Column('resource_type', sa.String(32), nullable=True),
        sa.Column('resource_id', sa.String(64), nullable=True),
        sa.Column('target_user_id', _UUID, nullable=True),
        sa.Column('ip_address', sa.String(64), nullable=True),
        sa.Column('user_agent', sa.String(512), nullable=True),
        sa.Column('request_id', sa.String(36), nullable=True),
        sa.Column('details', _JSONB, nullable=True),
    )
    op.create_index('ix_audit_logs_occurred_at', 'audit_logs', ['occurred_at'])
    op.create_index('ix_audit_logs_actor', 'audit_logs', ['actor_id', 'occurred_at'])
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    for statement in AUDIT_IMMUTABLE_STATEMENTS:
        op.execute(statement)

    op.create_table(
        'user_requests',
        sa.Column('request_id', _UUID, primary_key=True),
        sa.Column('user_id', _UUID, sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('payload', _JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('decided_by', _UUID, sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.String(1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_user_requests_user_id', 'user_requests', ['user_id'])
    op.create_index('ix_user_requests_status_type', 'user_requests', ['status', 'request_type'])
    op.create_index(
        'uq_user_requests_one_pending', 'user_requests', ['user_id', 'request_type'],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )


def _add_ownership_columns() -> None:
    for table in ('flow_recipes', 'process_recipes'):
        op.add_column(table, sa.Column(
            'owner_id', _UUID, sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True))
        op.add_column(table, sa.Column(
            'equipment_id', _UUID, sa.ForeignKey('equipment.equipment_id', ondelete='SET NULL'), nullable=True))
        op.create_index(f'ix_{table}_owner_id', table, ['owner_id'])
        op.create_index(f'ix_{table}_equipment_id', table, ['equipment_id'])
    op.add_column('modules', sa.Column(
        'owner_id', _UUID, sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_modules_owner_id', 'modules', ['owner_id'])
    op.execute(
        "UPDATE modules m SET owner_id = e.owner_id FROM equipment e "
        "WHERE m.equipment_id = e.equipment_id AND m.owner_id IS NULL"
    )


def _migrate_shares() -> None:
    """viewers/editors JSONB lists → resource_shares rows, then drop the columns."""
    conn = op.get_bind()
    insert = text(
        "INSERT INTO resource_shares (share_id, resource_type, resource_id, principal_type, "
        "principal_id, permission, granted_by) VALUES (:sid, :rtype, :rid, :ptype, :pid, :perm, :by) "
        "ON CONFLICT ON CONSTRAINT uq_resource_shares_principal DO NOTHING"
    )
    for table, pk, owner_col, rtype, has_editors in _SHARE_SOURCES:
        cols = f"{pk}, {owner_col}, viewers" + (", editors" if has_editors else "")
        for row in conn.execute(text(f"SELECT {cols} FROM {table}")).all():
            rid, owner = row[0], row[1]
            grants: dict[str, str] = {}
            for principal in (row[2] or []):
                grants[str(principal)] = 'view'
            if has_editors:
                for principal in (row[3] or []):
                    grants[str(principal)] = 'edit'
            for principal, perm in grants.items():
                if principal == str(owner):
                    continue  # the owner needs no share
                if principal == '*':
                    ptype, pid = 'public', '*'
                elif _is_uuid(principal):
                    ptype, pid = 'user', principal
                else:
                    continue  # garbage entry; nothing to grant
                conn.execute(insert, {
                    "sid": uuid.uuid4(), "rtype": rtype, "rid": str(rid), "ptype": ptype,
                    "pid": pid, "perm": perm, "by": owner,
                })
    op.drop_column('equipment', 'viewers')
    op.drop_column('equipment', 'editors')
    op.drop_column('simulators', 'viewers')
    op.drop_column('simulators', 'editors')
    op.drop_column('jobs', 'viewers')


def _promote_bootstrap_admins() -> None:
    from app.config import settings

    emails = sorted(settings.admin_emails)
    if not emails:
        return
    op.get_bind().execute(
        text("UPDATE users SET role = 'admin' WHERE lower(user_email) IN :emails")
        .bindparams(sa.bindparam('emails', expanding=True)),
        {"emails": emails},
    )


def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.String(32), nullable=False, server_default=sa.text("'user'")))
    op.add_column('users', sa.Column(
        'status', sa.String(32), nullable=False, server_default=sa.text("'pending_approval'")))
    # Everyone who could sign in before keeps being able to.
    op.execute("UPDATE users SET status = 'active' WHERE approved")
    _promote_bootstrap_admins()

    _create_tables()
    _add_ownership_columns()
    _migrate_shares()


def _restore_share_columns() -> None:
    conn = op.get_bind()
    op.add_column('equipment', sa.Column('viewers', _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('equipment', sa.Column('editors', _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('simulators', sa.Column('viewers', _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('simulators', sa.Column('editors', _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('jobs', sa.Column('viewers', _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    for table, pk, owner_col, rtype, has_editors in _SHARE_SOURCES:
        rows = conn.execute(text(
            "SELECT resource_id, principal_id, permission FROM resource_shares "
            "WHERE resource_type = :rtype AND principal_type IN ('user', 'public')"
        ), {"rtype": rtype}).all()
        by_resource: dict[str, dict[str, list[str]]] = {}
        for rid, pid, perm in rows:
            entry = by_resource.setdefault(rid, {"viewers": [], "editors": []})
            entry["viewers"].append(pid)
            if perm == 'edit':
                entry["editors"].append(pid)
        for rid, entry in by_resource.items():
            sets = "viewers = CAST(:viewers AS jsonb)" + (", editors = CAST(:editors AS jsonb)" if has_editors else "")
            params = {"viewers": json.dumps(entry["viewers"]), "rid": rid}
            if has_editors:
                params["editors"] = json.dumps(entry["editors"])
            conn.execute(text(f"UPDATE {table} SET {sets} WHERE CAST({pk} AS text) = :rid"), params)


def downgrade() -> None:
    _restore_share_columns()
    op.drop_index('ix_modules_owner_id', table_name='modules')
    op.drop_column('modules', 'owner_id')
    for table in ('process_recipes', 'flow_recipes'):
        op.drop_index(f'ix_{table}_equipment_id', table_name=table)
        op.drop_index(f'ix_{table}_owner_id', table_name=table)
        op.drop_column(table, 'equipment_id')
        op.drop_column(table, 'owner_id')
    op.drop_table('user_requests')
    for statement in AUDIT_IMMUTABLE_DROP_STATEMENTS:
        op.execute(statement)
    op.drop_table('audit_logs')
    op.drop_table('resource_shares')
    op.drop_table('group_members')
    op.drop_table('groups')
    op.drop_table('consent_records')
    op.drop_column('users', 'status')
    op.drop_column('users', 'role')
