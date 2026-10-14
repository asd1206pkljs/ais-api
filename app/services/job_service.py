import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import JobStatus, ResourceType, SharePermission
from app.enums import audit_action as act
from app.exceptions import (
    AuthorizationError,
    ConflictError,
    InsufficientCreditsError,
    NotFoundError,
)
from app.models.job import Job
from app.repositories.job_repository import JobRepository
from app.repositories.simulator_repository import SimulatorRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationMeta
from app.schemas.job import JobAdminRead, JobCreate, JobRead, JobStatusUpdate, JobUpdate
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit
from app.services.file_storage_service import FileStorageService, file_storage
from app.services.sharing_service import SharingService

RTYPE = ResourceType.JOB.value


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


def _admin_read(job: Job, user_email: str) -> JobAdminRead:
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


class JobService:
    def __init__(
        self,
        repo: JobRepository,
        user_repo: UserRepository | None = None,
        storage: FileStorageService = file_storage,
        access: AccessPolicy = access_policy,
        sharing: SharingService | None = None,
        audit_svc: AuditService = audit,
        simulator_repo: SimulatorRepository | None = None,
    ):
        self._repo = repo
        self._user_repo = user_repo or UserRepository()
        self._storage = storage
        self._access = access
        self._sharing = sharing or SharingService(access=access, audit_svc=audit_svc)
        self._audit = audit_svc
        self._simulators = simulator_repo or SimulatorRepository()

    # --- helpers ---------------------------------------------------------------

    async def _load(self, session: AsyncSession, job_id: int) -> Job:
        job = await self._repo.find_by_id(session, job_id)
        if job is None:
            raise NotFoundError("Job", str(job_id))
        return job

    async def _can_view(self, session, job: Job, user_id) -> bool:
        return await self._access.can_view(session, RTYPE, job.job_id, job.user_id, user_id)

    async def _reads(
        self, session: AsyncSession, rows: list[Job], viewer_id: uuid.UUID | None = None,
        emails: dict | None = None,
    ) -> list[JobRead]:
        lists = await self._sharing.access_lists(
            session, RTYPE, [str(j.job_id) for j in rows],
            viewer_id=viewer_id, owners={str(j.job_id): j.user_id for j in rows},
        )
        out = []
        for j in rows:
            viewers, _ = lists.get(str(j.job_id), ([], []))
            read = JobRead.model_validate(j)
            out.append(read.model_copy(update={
                "viewers": viewers,
                "user_email": (emails or {}).get(j.job_id),
            }))
        return out

    async def _read(self, session: AsyncSession, job: Job, viewer_id: uuid.UUID | None = None) -> JobRead:
        (read,) = await self._reads(session, [job], viewer_id)
        return read

    async def _require_simulator_view(self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID) -> None:
        simulator = await self._simulators.find_by_id(session, simulator_id)
        if simulator is None or simulator.save_status == "deleted":
            raise NotFoundError("Simulator", str(simulator_id))
        if not await self._access.can_view(
            session, ResourceType.SIMULATOR.value, simulator.simulator_id, simulator.owner_id, user_id
        ):
            raise AuthorizationError("No access to the selected simulator")

    # --- user operations ---------------------------------------------------------

    async def create(self, session: AsyncSession, user_id: uuid.UUID, data: JobCreate) -> JobRead:
        user = await self._user_repo.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        await self._require_simulator_view(session, data.simulator_id, user_id)

        deducted = await self._user_repo.try_deduct_credit(session, user_id, 1)
        if not deducted:
            await session.rollback()
            raise InsufficientCreditsError()

        try:
            job = await self._repo.create(session, {
                "user_id": user_id,
                "simulator_id": data.simulator_id,
                "job_name": data.job_name,
            })
        except Exception:
            await session.rollback()
            raise

        # Provision the per-job result directory and persist its absolute path.
        result_dir = self._storage.job_result_dir(job.job_id)
        updated = await self._repo.update(session, job.job_id, {"result_path": result_dir})
        await self._audit.record(session, act.JOB_CREATED, resource_type=RTYPE, resource_id=job.job_id,
                                 details={"simulator_id": data.simulator_id, "name": data.job_name})
        return await self._read(session, updated or job, user_id)

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> tuple[list[JobRead], PaginationMeta]:
        if await self._access.is_admin(session, user_id):
            rows = await self._repo.find_all_newest_with_user(session, skip, limit)
            total = await self._repo.count(session)
            jobs = [j for j, _ in rows]
            emails = {j.job_id: email for j, email in rows}
            return await self._reads(session, jobs, user_id, emails), _meta(total, skip, limit)
        principals = await self._access.principals(session, user_id)
        jobs = await self._repo.find_accessible_by_user(session, user_id, principals, skip, limit)
        total = await self._repo.count_accessible_by_user(session, user_id, principals)
        return await self._reads(session, jobs, user_id), _meta(total, skip, limit)

    async def get(self, session: AsyncSession, job_id: int, user_id: uuid.UUID) -> JobRead:
        """Job metadata: owner, viewers, or an admin (admin console)."""
        job = await self._load(session, job_id)
        if not await self._can_view(session, job, user_id) and not await self._access.is_admin(session, user_id):
            raise AuthorizationError()
        return await self._read(session, job, user_id)

    async def get_result_path(self, session: AsyncSession, job_id: int, user_id: uuid.UUID) -> str | None:
        """Result bundle location for the result endpoints. Results are user data,
        so only the owner and people the job was shared with may read them."""
        job = await self._load(session, job_id)
        if not await self._can_view(session, job, user_id):
            raise AuthorizationError()
        await self._audit.record(session, act.RESOURCE_READ, resource_type=RTYPE, resource_id=job_id,
                                 details={"part": "results"})
        return job.result_path

    async def update(self, session: AsyncSession, job_id: int, user_id: uuid.UUID, data: JobUpdate) -> JobRead:
        job = await self._load(session, job_id)
        if not self._access.is_owner(job.user_id, user_id):
            raise AuthorizationError()
        changes = data.model_dump(exclude_none=True)
        updated = await self._repo.update(session, job_id, changes)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=job_id,
                                 details=changes)
        return await self._read(session, updated, user_id)

    async def request_cancel(self, session: AsyncSession, job_id: int, user_id: uuid.UUID) -> dict:
        """Lock a pending job for cancellation by transitioning to paused.

        Returns {"paused": bool, "current_status": str, "refundable_on_delete": bool}.
        """
        job = await self._load(session, job_id)
        if not self._access.is_owner(job.user_id, user_id):
            raise AuthorizationError()

        paused = await self._repo.try_transition_status(session, job_id, JobStatus.PENDING, JobStatus.PAUSED)
        if paused:
            await session.commit()
            await self._audit.record(session, act.JOB_CANCEL_REQUESTED, resource_type=RTYPE, resource_id=job_id)
            return {"paused": True, "current_status": JobStatus.PAUSED.value, "refundable_on_delete": True}

        await session.refresh(job)
        return {"paused": False, "current_status": str(job.job_status), "refundable_on_delete": False}

    async def resume(self, session: AsyncSession, job_id: int, user_id: uuid.UUID) -> dict:
        """Revert a user-paused job back to pending."""
        job = await self._load(session, job_id)
        if not self._access.is_owner(job.user_id, user_id):
            raise AuthorizationError()

        resumed = await self._repo.try_transition_status(session, job_id, JobStatus.PAUSED, JobStatus.PENDING)
        if resumed:
            await session.commit()
            await self._audit.record(session, act.JOB_RESUMED, resource_type=RTYPE, resource_id=job_id)
            return {"resumed": True, "current_status": JobStatus.PENDING.value}

        await session.refresh(job)
        return {"resumed": False, "current_status": str(job.job_status)}

    async def delete(self, session: AsyncSession, job_id: int, user_id: uuid.UUID) -> dict:
        """Delete a job. Refund 1 credit only if the job was pending or paused.

        Returns: {"refunded": bool, "previous_status": str}.
        """
        job = await self._load(session, job_id)
        if not self._access.is_owner(job.user_id, user_id):
            raise AuthorizationError()

        previous_status = str(job.job_status)
        refundable = previous_status in (JobStatus.PENDING.value, JobStatus.PAUSED.value)
        if refundable:
            await self._user_repo.refund_credit(session, user_id, 1)

        await self._sharing.delete_for_resource(session, RTYPE, job_id)
        await self._repo.delete(session, job_id)
        await self._audit.record(session, act.JOB_DELETED, resource_type=RTYPE, resource_id=job_id,
                                 details={"refunded": refundable, "previous_status": previous_status})
        return {"refunded": refundable, "previous_status": previous_status}

    # --- legacy sharing endpoints ----------------------------------------------------

    async def add_viewer(self, session, job_id: int, owner_id, viewer_id: str) -> JobRead:
        await self._sharing.grant_legacy(session, RTYPE, str(job_id), owner_id, viewer_id, SharePermission.VIEW)
        return await self._read(session, await self._load(session, job_id), owner_id)

    async def remove_viewer(self, session, job_id: int, owner_id, viewer_id: str) -> JobRead:
        await self._sharing.revoke_legacy(session, RTYPE, str(job_id), owner_id, viewer_id, SharePermission.VIEW)
        return await self._read(session, await self._load(session, job_id), owner_id)

    # --- internal (training servers, API key) -------------------------------------------

    async def admin_list_by_statuses(
        self, session: AsyncSession, statuses: list[JobStatus], skip: int = 0, limit: int = 10
    ) -> tuple[list[JobAdminRead], PaginationMeta]:
        rows = await self._repo.find_by_statuses_with_user(session, statuses, skip, limit)
        total = await self._repo.count_by_statuses(session, statuses)
        return [_admin_read(job, email) for job, email in rows], _meta(total, skip, limit)

    async def admin_get(self, session: AsyncSession, job_id: int) -> JobAdminRead:
        row = await self._repo.find_by_id_with_user(session, job_id)
        if row is None:
            raise NotFoundError("Job", str(job_id))
        return _admin_read(*row)

    async def admin_claim(self, session: AsyncSession, job_id: int, claimed_by: str) -> JobRead:
        """Atomically claim a pending job for a training server (409 if not pending)."""
        job = await self._load(session, job_id)
        claimed = await self._repo.try_claim(session, job_id, claimed_by)
        if not claimed:
            await session.refresh(job)
            raise ConflictError(
                f"Job {job_id} is not pending (current: {job.job_status}, claimed_by: {job.claimed_by})"
            )
        await session.commit()
        await self._audit.record(session, act.JOB_STATUS_CHANGED, resource_type=RTYPE, resource_id=job_id,
                                 details={"job_status": JobStatus.TRAINING.value, "claimed_by": claimed_by})
        return await self._read(session, await self._load(session, job_id))

    async def admin_set_status(self, session: AsyncSession, job_id: int, data: JobStatusUpdate) -> JobRead:
        await self._load(session, job_id)
        values: dict = {"job_status": data.job_status.value}
        if data.job_status == JobStatus.PENDING:
            values["claimed_by"] = None  # 선점 해제: 다른 서버가 다시 잡을 수 있음
        updated = await self._repo.update(session, job_id, values)
        await self._audit.record(session, act.JOB_STATUS_CHANGED, resource_type=RTYPE, resource_id=job_id,
                                 details=values)
        return await self._read(session, updated)
