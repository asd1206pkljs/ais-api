from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_internal
from app.enums import JobStatus
from app.middleware import limiter
from app.repositories.job_repository import JobRepository
from app.schemas.common import APIResponse
from app.schemas.job import (
    JobAccessUserRequest,
    JobAdminRead,
    JobClaimRequest,
    JobCreate,
    JobRead,
    JobStatusUpdate,
    JobUpdate,
)
from app.schemas.user import UserRead
from app.services import job_result_service
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
_repo = JobRepository()


def _get_service() -> JobService:
    return JobService(_repo)


@router.post("", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def create_job(
    request: Request,
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    job = await svc.create(db, current_user.user_id, body)
    return APIResponse.ok(job)


@router.get("", response_model=APIResponse[list[JobRead]])
@limiter.limit("60/minute")
async def list_jobs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    jobs, meta = await svc.list_for_user(db, current_user.user_id, skip, limit)
    return APIResponse.ok(jobs, meta)


@router.get("/admin/by-status", response_model=APIResponse[list[JobAdminRead]])
@limiter.limit("60/minute")
async def admin_list_by_status(
    request: Request,
    statuses: list[JobStatus] = Query(default=[JobStatus.PENDING]),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_internal),
):
    """Internal-only listing of jobs filtered by status (newest first)."""
    svc = _get_service()
    jobs, meta = await svc.admin_list_by_statuses(db, statuses, skip, limit)
    return APIResponse.ok(jobs, meta)


@router.get("/admin/{job_id}", response_model=APIResponse[JobAdminRead])
@limiter.limit("60/minute")
async def admin_get_job(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_internal),
):
    """Internal-only: fetch a single job (with owner email and result_path)."""
    svc = _get_service()
    job = await svc.admin_get(db, job_id)
    return APIResponse.ok(job)


@router.post("/admin/{job_id}/claim", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def admin_claim_job(
    request: Request,
    job_id: int,
    body: JobClaimRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_internal),
):
    """Internal-only: atomically claim a pending job (pending→training + claimed_by).

    409 if the job is no longer pending — e.g. another training server claimed it
    first. Launchers must use this instead of PATCH /status to avoid double-claims.
    """
    svc = _get_service()
    job = await svc.admin_claim(db, job_id, body.claimed_by)
    return APIResponse.ok(job)


@router.patch("/admin/{job_id}/status", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def admin_set_status(
    request: Request,
    job_id: int,
    body: JobStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_internal),
):
    """Internal-only direct status update (used by the launcher to mark training/complete/failed)."""
    svc = _get_service()
    job = await svc.admin_set_status(db, job_id, body)
    return APIResponse.ok(job)


@router.get("/{job_id}", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def get_job(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    job = await svc.get(db, job_id, current_user.user_id)
    return APIResponse.ok(job)


@router.get("/{job_id}/results/summary", response_model=APIResponse[list[dict]])
@limiter.limit("60/minute")
async def get_job_result_summary(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Training summary (scatter-plot points) from the job's result_path bundle."""
    svc = _get_service()
    job = await svc.get(db, job_id, current_user.user_id)
    return APIResponse.ok(job_result_service.get_summary(job.result_path))


@router.get("/{job_id}/results/episodes", response_model=APIResponse[list[str]])
@limiter.limit("60/minute")
async def list_job_result_episodes(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Episode names available in the job's result_path bundle (for gantt)."""
    svc = _get_service()
    job = await svc.get(db, job_id, current_user.user_id)
    return APIResponse.ok(job_result_service.list_episodes(job.result_path))


@router.get("/{job_id}/results/gantt-config", response_model=APIResponse[dict])
@limiter.limit("60/minute")
async def get_job_result_gantt_config(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """exp-web's saved gantt row config from the job's result_path bundle ({} if none)."""
    svc = _get_service()
    job = await svc.get(db, job_id, current_user.user_id)
    return APIResponse.ok(job_result_service.get_gantt_config(job.result_path))


@router.get(
    "/{job_id}/results/episodes/{ep_name}/logs",
    response_model=APIResponse[list[dict]],
)
@limiter.limit("60/minute")
async def get_job_result_episode_logs(
    request: Request,
    job_id: int,
    ep_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Gantt bars for one episode from the job's result_path bundle."""
    svc = _get_service()
    job = await svc.get(db, job_id, current_user.user_id)
    return APIResponse.ok(job_result_service.get_episode_logs(job.result_path, ep_name))


@router.put("/{job_id}", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def update_job(
    request: Request,
    job_id: int,
    body: JobUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    job = await svc.update(db, job_id, current_user.user_id, body)
    return APIResponse.ok(job)


@router.post("/{job_id}/request-cancel", response_model=APIResponse[dict])
@limiter.limit("60/minute")
async def request_cancel_job(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    result = await svc.request_cancel(db, job_id, current_user.user_id)
    return APIResponse.ok(result)


@router.post("/{job_id}/resume", response_model=APIResponse[dict])
@limiter.limit("60/minute")
async def resume_job(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    result = await svc.resume(db, job_id, current_user.user_id)
    return APIResponse.ok(result)


@router.delete("/{job_id}", response_model=APIResponse[dict])
@limiter.limit("60/minute")
async def delete_job(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    result = await svc.delete(db, job_id, current_user.user_id)
    return APIResponse.ok(result)


@router.post("/{job_id}/viewers", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def add_viewer(
    request: Request,
    job_id: int,
    body: JobAccessUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    job = await svc.add_viewer(db, job_id, current_user.user_id, body.user_id)
    return APIResponse.ok(job)


@router.delete("/{job_id}/viewers/{viewer_id}", response_model=APIResponse[JobRead])
@limiter.limit("60/minute")
async def remove_viewer(
    request: Request,
    job_id: int,
    viewer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    job = await svc.remove_viewer(db, job_id, current_user.user_id, viewer_id)
    return APIResponse.ok(job)


