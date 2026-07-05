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
    JobCreate,
    JobRead,
    JobStatusUpdate,
    JobUpdate,
)
from app.schemas.user import UserRead
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


