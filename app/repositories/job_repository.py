import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import JobStatus
from app.models.job import Job
from app.models.user import User
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    def __init__(self):
        super().__init__(Job)

    async def find_by_id(self, session: AsyncSession, entity_id: int) -> Job | None:
        result = await session.execute(select(Job).where(Job.job_id == entity_id))
        return result.scalar_one_or_none()

    async def find_all_newest_with_user(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> list[tuple[Job, str]]:
        """(job, user_email) for all jobs, newest first — used for admin listing."""
        result = await session.execute(
            select(Job, User.user_email)
            .join(User, Job.user_id == User.user_id)
            .order_by(Job.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def find_by_id_with_user(
        self, session: AsyncSession, entity_id: int
    ) -> tuple[Job, str] | None:
        """Return (job, user_email) for a single job, or None if missing."""
        result = await session.execute(
            select(Job, User.user_email)
            .join(User, Job.user_id == User.user_id)
            .where(Job.job_id == entity_id)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def find_by_statuses_with_user(
        self,
        session: AsyncSession,
        statuses: list[JobStatus],
        skip: int = 0,
        limit: int = 10,
    ) -> list[tuple[Job, str]]:
        """Return (job, user_email) tuples filtered by status, newest first."""
        status_values = [s.value for s in statuses]
        result = await session.execute(
            select(Job, User.user_email)
            .join(User, Job.user_id == User.user_id)
            .where(Job.job_status.in_(status_values))
            .order_by(Job.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def count_by_statuses(
        self, session: AsyncSession, statuses: list[JobStatus]
    ) -> int:
        status_values = [s.value for s in statuses]
        result = await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.job_status.in_(status_values))
        )
        return result.scalar_one()

    async def find_by_user_id(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Job]:
        result = await session.execute(
            select(Job).where(Job.user_id == user_id).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_user_id(self, session: AsyncSession, user_id: uuid.UUID) -> int:
        result = await session.execute(
            select(func.count()).select_from(Job).where(Job.user_id == user_id)
        )
        return result.scalar_one()

    async def find_accessible_by_user(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Job]:
        uid_str = str(user_id)
        result = await session.execute(
            select(Job)
            .where(
                or_(
                    Job.user_id == user_id,
                    Job.viewers.contains([uid_str]),
                    Job.viewers.contains(["*"]),
                ),
            )
            .order_by(Job.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_accessible_by_user(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> int:
        uid_str = str(user_id)
        result = await session.execute(
            select(func.count())
            .select_from(Job)
            .where(
                or_(
                    Job.user_id == user_id,
                    Job.viewers.contains([uid_str]),
                    Job.viewers.contains(["*"]),
                ),
            )
        )
        return result.scalar_one()

    async def try_transition_status(
        self,
        session: AsyncSession,
        job_id: int,
        from_status: JobStatus,
        to_status: JobStatus,
    ) -> bool:
        """Atomically transition status from `from_status` to `to_status`.

        Returns True if the row was updated. False means the job is no longer
        in `from_status` (status changed in between) or does not exist.
        Caller is responsible for commit/rollback.
        """
        result = await session.execute(
            update(Job)
            .where(Job.job_id == job_id, Job.job_status == from_status.value)
            .values(job_status=to_status.value)
        )
        return result.rowcount > 0
