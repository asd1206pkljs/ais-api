"""Backfill result_path on in-flight jobs.

For every job whose status is pending / training / paused and whose result_path
is NULL, set result_path = `${TRAIN_RESULTS_BASE_PATH}/${job_id}` and create the
directory on disk. Idempotent — running it again only touches rows still
missing a path.

Usage:
    cd /home/ais/ais-api
    conda run -n api-server python scripts/backfill_job_result_path.py

Use --include-finished to also backfill complete/failed jobs (useful for
inspecting historical results).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import bindparam, text

from app.config import settings
from app.database import async_session_factory


ACTIVE_STATUSES = ("pending", "training", "paused")
ALL_STATUSES = ACTIVE_STATUSES + ("complete", "failed")


async def backfill(statuses: tuple[str, ...]) -> None:
    base = Path(settings.TRAIN_RESULTS_BASE_PATH)
    base.mkdir(parents=True, exist_ok=True)

    select_stmt = text(
        "SELECT job_id FROM jobs "
        "WHERE result_path IS NULL AND job_status IN :statuses"
    ).bindparams(bindparam("statuses", expanding=True))
    update_stmt = text("UPDATE jobs SET result_path = :p WHERE job_id = :id")

    async with async_session_factory() as session:
        rows = (
            await session.execute(select_stmt, {"statuses": list(statuses)})
        ).fetchall()

        if not rows:
            print("No jobs need backfilling.")
            return

        for (job_id,) in rows:
            target = base / str(job_id)
            target.mkdir(parents=True, exist_ok=True)
            await session.execute(update_stmt, {"p": str(target), "id": job_id})

        await session.commit()
        print(f"Updated {len(rows)} job(s) under {base}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--include-finished",
        action="store_true",
        help="Also backfill complete/failed jobs.",
    )
    args = parser.parse_args()

    statuses = ALL_STATUSES if args.include_finished else ACTIVE_STATUSES
    asyncio.run(backfill(statuses))


if __name__ == "__main__":
    main()
