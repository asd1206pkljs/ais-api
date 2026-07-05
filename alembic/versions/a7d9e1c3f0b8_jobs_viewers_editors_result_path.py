"""jobs: add viewers, result_path

Revision ID: a7d9e1c3f0b8
Revises: f6a9b2d1c8e4
Create Date: 2026-05-13 00:00:00.000000

"""
import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'a7d9e1c3f0b8'
down_revision = 'f6a9b2d1c8e4'
branch_labels = None
depends_on = None

# Statuses considered "in flight" — pending / training / paused.
# We backfill result_path and create the result directory on disk for these
# so the launcher can write outputs to a known location after upgrade.
ACTIVE_STATUSES = ('pending', 'training', 'paused')


def upgrade() -> None:
    op.add_column(
        'jobs',
        sa.Column('viewers', JSONB, nullable=False, server_default='[]'),
    )
    op.add_column(
        'jobs',
        sa.Column('result_path', sa.String(length=1024), nullable=True),
    )

    # Backfill: seed owner into viewers for existing rows
    op.execute("""
        UPDATE jobs
        SET viewers = jsonb_build_array(user_id::text)
        WHERE viewers = '[]'::jsonb
    """)

    # Backfill result_path for active (in-flight) jobs and create the dirs.
    base = Path(os.environ.get(
        "TRAIN_RESULTS_BASE_PATH", "/home/ais/ais-api/train_results"
    ))
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT job_id FROM jobs "
            "WHERE result_path IS NULL AND job_status IN :statuses"
        ).bindparams(sa.bindparam("statuses", expanding=True)),
        {"statuses": list(ACTIVE_STATUSES)},
    ).fetchall()

    for (job_id,) in rows:
        target = base / str(job_id)
        target.mkdir(parents=True, exist_ok=True)
        bind.execute(
            sa.text("UPDATE jobs SET result_path = :p WHERE job_id = :id"),
            {"p": str(target), "id": job_id},
        )


def downgrade() -> None:
    op.drop_column('jobs', 'result_path')
    op.drop_column('jobs', 'viewers')
