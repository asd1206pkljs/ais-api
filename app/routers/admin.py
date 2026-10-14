"""Admin console API. Every endpoint requires the platform admin role and
returns account/resource *metadata* only — never user data content."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.enums import RequestStatus, RequestType, ResourceType, UserRole, UserStatus
from app.middleware import limiter
from app.repositories.audit_log_repository import AuditLogRepository, AuditQuery
from app.repositories.resource_share_repository import ResourceShareRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_request_repository import UserRequestRepository
from app.schemas.admin import AdminStats, AdminUserRead, AdminUserUpdate, CreditAdjustment
from app.schemas.audit import AuditLogRead
from app.schemas.common import APIResponse, PaginationMeta
from app.schemas.group import GroupRead
from app.schemas.request import RequestAdminRead, RequestDecision
from app.schemas.share import ShareAdminRead
from app.schemas.user import UserRead
from app.services.admin_user_service import AdminUserService
from app.services.group_service import GroupService
from app.services.request_service import RequestService
from app.services.sharing_service import SharingService

router = APIRouter(prefix="/admin", tags=["admin"])


# --- users ---------------------------------------------------------------------


@router.get("/users", response_model=APIResponse[list[AdminUserRead]])
@limiter.limit("60/minute")
async def list_users(
    request: Request,
    status: UserStatus | None = Query(None),
    role: UserRole | None = Query(None),
    q: str | None = Query(None, max_length=255, description="email / name / company contains"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    items, meta = await AdminUserService().list_users(
        db, status=status.value if status else None, role=role.value if role else None, q=q, skip=skip, limit=limit
    )
    return APIResponse.ok(items, meta)


@router.get("/users/{user_id}", response_model=APIResponse[AdminUserRead])
@limiter.limit("60/minute")
async def get_user(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    return APIResponse.ok(await AdminUserService().get_user(db, user_id))


@router.patch("/users/{user_id}", response_model=APIResponse[AdminUserRead])
@limiter.limit("30/minute")
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: UserRead = Depends(require_admin),
):
    """Change role (admin/user) or status (active/disabled). Disabling ends all sessions."""
    return APIResponse.ok(await AdminUserService().update_user(db, admin.user_id, user_id, body))


@router.post("/users/{user_id}/credits", response_model=APIResponse[AdminUserRead])
@limiter.limit("30/minute")
async def adjust_credits(
    request: Request,
    user_id: uuid.UUID,
    body: CreditAdjustment,
    db: AsyncSession = Depends(get_db),
    admin: UserRead = Depends(require_admin),
):
    return APIResponse.ok(await AdminUserService().adjust_credits(db, admin.user_id, user_id, body))


# --- requests --------------------------------------------------------------------


@router.get("/requests", response_model=APIResponse[list[RequestAdminRead]])
@limiter.limit("60/minute")
async def list_requests(
    request: Request,
    status: RequestStatus | None = Query(RequestStatus.PENDING),
    request_type: RequestType | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    items, meta = await RequestService().list_all(
        db, status.value if status else None, request_type.value if request_type else None, skip, limit
    )
    return APIResponse.ok(items, meta)


@router.post("/requests/{request_id}/approve", response_model=APIResponse[RequestAdminRead])
@limiter.limit("30/minute")
async def approve_request(
    request: Request,
    request_id: uuid.UUID,
    body: RequestDecision | None = None,
    db: AsyncSession = Depends(get_db),
    admin: UserRead = Depends(require_admin),
):
    return APIResponse.ok(
        await RequestService().approve(db, admin.user_id, request_id, body or RequestDecision())
    )


@router.post("/requests/{request_id}/reject", response_model=APIResponse[RequestAdminRead])
@limiter.limit("30/minute")
async def reject_request(
    request: Request,
    request_id: uuid.UUID,
    body: RequestDecision | None = None,
    db: AsyncSession = Depends(get_db),
    admin: UserRead = Depends(require_admin),
):
    return APIResponse.ok(
        await RequestService().reject(db, admin.user_id, request_id, body or RequestDecision())
    )


# --- groups / sharing overview ---------------------------------------------------


@router.get("/groups", response_model=APIResponse[list[GroupRead]])
@limiter.limit("60/minute")
async def list_groups(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    items, meta = await GroupService().list_all(db, skip, limit)
    return APIResponse.ok(items, meta)


@router.get("/shares", response_model=APIResponse[list[ShareAdminRead]])
@limiter.limit("60/minute")
async def list_shares(
    request: Request,
    public_only: bool = Query(False),
    resource_type: ResourceType | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    """Sharing overview; `public_only=true` lists everything exposed to all users."""
    items, meta = await SharingService().list_all(
        db, public_only=public_only, resource_type=resource_type.value if resource_type else None,
        skip=skip, limit=limit,
    )
    return APIResponse.ok(items, meta)


@router.delete("/shares/{share_id}", response_model=APIResponse[None])
@limiter.limit("30/minute")
async def revoke_share(
    request: Request,
    share_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    await SharingService().admin_revoke(db, share_id)
    return APIResponse.ok(None)


# --- audit log --------------------------------------------------------------------


@router.get("/audit-logs", response_model=APIResponse[list[AuditLogRead]])
@limiter.limit("60/minute")
async def list_audit_logs(
    request: Request,
    actor_id: uuid.UUID | None = Query(None),
    target_user_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=64),
    action_prefix: str | None = Query(None, max_length=64, description="e.g. `auth.` or `share.`"),
    resource_type: str | None = Query(None, max_length=32),
    resource_id: str | None = Query(None, max_length=64),
    outcome: str | None = Query(None, max_length=16),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    q = AuditQuery(
        actor_id=actor_id, target_user_id=target_user_id, action=action, action_prefix=action_prefix,
        resource_type=resource_type, resource_id=resource_id, outcome=outcome, since=since, until=until,
    )
    repo = AuditLogRepository()
    rows = await repo.search(db, q, skip, limit)
    total = await repo.count(db, q)
    pages = (total + limit - 1) // limit
    meta = PaginationMeta(total=total, page=(skip // limit) + 1, limit=limit, pages=pages)
    return APIResponse.ok([AuditLogRead.model_validate(r) for r in rows], meta)


# --- dashboard --------------------------------------------------------------------


@router.get("/stats", response_model=APIResponse[AdminStats])
@limiter.limit("60/minute")
async def stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    users = UserRepository()
    return APIResponse.ok(AdminStats(
        users_total=await users.count_search(db),
        users_pending_approval=await users.count_search(db, status=UserStatus.PENDING_APPROVAL.value),
        requests_pending=await UserRequestRepository().count(db, status=RequestStatus.PENDING.value),
        public_shares=await ResourceShareRepository().count_all(db, public_only=True),
    ))
