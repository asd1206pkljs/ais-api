import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import JobStatus
from app.exceptions import (
    AuthorizationError,
    ConflictError,
    InsufficientCreditsError,
    NotFoundError,
)
from app.repositories.job_repository import JobRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationMeta
from app.schemas.job import JobAdminRead, JobCreate, JobRead, JobStatusUpdate, JobUpdate
from app.services.access import is_admin
from app.services.file_storage_service import FileStorageService, file_storage


class JobService:
    def __init__(
        self,
        repo: JobRepository,
        user_repo: UserRepository | None = None,
        storage: FileStorageService = file_storage,
    ):
        self._repo = repo
        self._user_repo = user_repo or UserRepository()
        self._storage = storage

    def _can_view(self, job, user_id: uuid.UUID) -> bool:
        uid = str(user_id)
        viewers = job.viewers or []
        return job.user_id == user_id or "*" in viewers or uid in viewers

    def _is_owner(self, job, user_id: uuid.UUID) -> bool:
        return job.user_id == user_id

    async def create(
        self, session: AsyncSession, user_id: uuid.UUID, data: JobCreate
    ) -> JobRead:
        user = await self._user_repo.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))

        deducted = await self._user_repo.try_deduct_credit(session, user_id, 1)
        if not deducted:
            await session.rollback()
            raise InsufficientCreditsError()

        owner_str = str(user_id)
        try:
            job = await self._repo.create(session, {
                "user_id": user_id,
                "simulator_id": data.simulator_id,
                "job_name": data.job_name,
                "viewers": [owner_str],
            })
        except Exception:
            await session.rollback()
            raise

        # Provision the per-job result directory and persist its absolute path.
        result_dir = self._storage.job_result_dir(job.job_id)
        updated = await self._repo.update(session, job.job_id, {"result_path": result_dir})
        return JobRead.model_validate(updated or job)

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> tuple[list[JobRead], PaginationMeta]:
        if await is_admin(session, user_id):
            rows = await self._repo.find_all_newest_with_user(session, skip, limit)
            total = await self._repo.count(session)
            pages = (total + limit - 1) // limit if limit > 0 else 0
            meta = PaginationMeta(total=total, page=(skip // limit) + 1, limit=limit, pages=pages)
            items = [
                JobRead.model_validate({
                    "job_id": j.job_id,
                    "user_id": j.user_id,
                    "user_email": email,
                    "simulator_id": j.simulator_id,
                    "job_name": j.job_name,
                    "job_status": j.job_status,
                    "viewers": j.viewers,
                    "result_path": j.result_path,
                    "created_at": j.created_at,
                    "updated_at": j.updated_at,
                })
                for j, email in rows
            ]
            return items, meta
        jobs = await self._repo.find_accessible_by_user(session, user_id, skip, limit)
        total = await self._repo.count_accessible_by_user(session, user_id)
        pages = (total + limit - 1) // limit if limit > 0 else 0
        meta = PaginationMeta(total=total, page=(skip // limit) + 1, limit=limit, pages=pages)
        return [JobRead.model_validate(j) for j in jobs], meta

    async def get(
        self, session: AsyncSession, job_id: int, user_id: uuid.UUID
    ) -> JobRead:
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._can_view(job, user_id) and not await is_admin(session, user_id):
            raise AuthorizationError()
        return JobRead.model_validate(job)

    async def update(
        self, session: AsyncSession, job_id: int, user_id: uuid.UUID, data: JobUpdate
    ) -> JobRead:
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._is_owner(job, user_id):
            raise AuthorizationError()
        updated = await self._repo.update(session, job_id, data.model_dump(exclude_none=True))
        return JobRead.model_validate(updated)

    async def request_cancel(
        self, session: AsyncSession, job_id: int, user_id: uuid.UUID
    ) -> dict:
        """Lock a pending job for cancellation by transitioning to paused.

        While paused, the worker must not pick up the job. The frontend then
        prompts the user; on confirm `delete` refunds the credit, on abort
        `resume` returns the job to pending.

        Returns: {
          "paused": bool,            # True iff status was atomically pending->paused
          "current_status": str,     # current status after attempted transition
          "refundable_on_delete": bool,
        }
        """
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._is_owner(job, user_id):
            raise AuthorizationError()

        paused = await self._repo.try_transition_status(
            session, job_id, JobStatus.PENDING, JobStatus.PAUSED
        )
        if paused:
            await session.commit()
            return {
                "paused": True,
                "current_status": JobStatus.PAUSED.value,
                "refundable_on_delete": True,
            }

        # Status changed before we could lock it; report the latest state.
        await session.refresh(job)
        return {
            "paused": False,
            "current_status": str(job.job_status),
            "refundable_on_delete": False,
        }

    async def resume(
        self, session: AsyncSession, job_id: int, user_id: uuid.UUID
    ) -> dict:
        """Revert a user-paused job back to pending (used when the user aborts the cancel dialog)."""
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._is_owner(job, user_id):
            raise AuthorizationError()

        resumed = await self._repo.try_transition_status(
            session, job_id, JobStatus.PAUSED, JobStatus.PENDING
        )
        if resumed:
            await session.commit()
            return {"resumed": True, "current_status": JobStatus.PENDING.value}

        await session.refresh(job)
        return {"resumed": False, "current_status": str(job.job_status)}

    async def admin_list_by_statuses(
        self,
        session: AsyncSession,
        statuses: list[JobStatus],
        skip: int = 0,
        limit: int = 10,
    ) -> tuple[list[JobAdminRead], PaginationMeta]:
        rows = await self._repo.find_by_statuses_with_user(session, statuses, skip, limit)
        total = await self._repo.count_by_statuses(session, statuses)
        pages = (total + limit - 1) // limit if limit > 0 else 0
        items = [
            JobAdminRead.model_validate({
                "job_id": job.job_id,
                "user_id": job.user_id,
                "user_email": user_email,
                "simulator_id": job.simulator_id,
                "job_name": job.job_name,
                "job_status": job.job_status,
                "claimed_by": job.claimed_by,
                "result_path": job.result_path,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            })
            for job, user_email in rows
        ]
        meta = PaginationMeta(
            total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages
        )
        return items, meta

    async def admin_get(
        self, session: AsyncSession, job_id: int
    ) -> JobAdminRead:
        """Internal-only: fetch a single job with the owner's email."""
        row = await self._repo.find_by_id_with_user(session, job_id)
        if row is None:
            raise NotFoundError("Job", str(job_id))
        job, user_email = row
        return JobAdminRead.model_validate({
            "job_id": job.job_id,
            "user_id": job.user_id,
            "user_email": user_email,
            "simulator_id": job.simulator_id,
            "job_name": job.job_name,
            "job_status": job.job_status,
            "claimed_by": job.claimed_by,
            "result_path": job.result_path,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        })

    async def admin_claim(
        self, session: AsyncSession, job_id: int, claimed_by: str
    ) -> JobRead:
        """Internal-only: atomically claim a pending job for a training server.

        Raises ConflictError if the job is not pending anymore (e.g. another
        server claimed it first).
        """
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))

        claimed = await self._repo.try_claim(session, job_id, claimed_by)
        if not claimed:
            await session.refresh(job)
            raise ConflictError(
                f"Job {job_id} is not pending (current: {job.job_status}, "
                f"claimed_by: {job.claimed_by})"
            )
        await session.commit()
        updated = await self._repo.find_by_id(session, job_id)
        return JobRead.model_validate(updated)

    async def admin_set_status(
        self, session: AsyncSession, job_id: int, data: JobStatusUpdate
    ) -> JobRead:
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        values: dict = {"job_status": data.job_status.value}
        if data.job_status == JobStatus.PENDING:
            # pending으로 되돌리면 선점 기록도 해제 (다른 서버가 다시 잡을 수 있음)
            values["claimed_by"] = None
        updated = await self._repo.update(session, job_id, values)
        return JobRead.model_validate(updated)

    async def delete(
        self, session: AsyncSession, job_id: int, user_id: uuid.UUID
    ) -> dict:
        """Delete a job. Refund 1 credit only if the job was pending or paused.

        `paused` always originates from a user-cancelled pending job, so refunding
        on paused is safe. `pending` is also refunded as a defensive fallback for
        callers that hit DELETE without the request-cancel flow.

        Returns: {"refunded": bool, "previous_status": str}.
        """
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._is_owner(job, user_id):
            raise AuthorizationError()

        previous_status = str(job.job_status)
        refundable = previous_status in (JobStatus.PENDING.value, JobStatus.PAUSED.value)

        if refundable:
            await self._user_repo.refund_credit(session, user_id, 1)

        await self._repo.delete(session, job_id)
        return {"refunded": refundable, "previous_status": previous_status}

    async def add_viewer(
        self, session: AsyncSession, job_id: int, owner_id: uuid.UUID, viewer_id: str
    ) -> JobRead:
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._is_owner(job, owner_id):
            raise AuthorizationError("Only the owner can manage viewers")
        current = list(job.viewers or [])
        new_viewers = current if viewer_id in current else [*current, viewer_id]
        updated = await self._repo.update(session, job_id, {"viewers": new_viewers})
        return JobRead.model_validate(updated)

    async def remove_viewer(
        self, session: AsyncSession, job_id: int, owner_id: uuid.UUID, viewer_id: str
    ) -> JobRead:
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        if not self._is_owner(job, owner_id):
            raise AuthorizationError("Only the owner can manage viewers")
        new_viewers = [v for v in (job.viewers or []) if v != viewer_id]
        updated = await self._repo.update(session, job_id, {"viewers": new_viewers})
        return JobRead.model_validate(updated)

