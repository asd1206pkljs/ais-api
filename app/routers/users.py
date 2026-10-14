from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.enums import RequestStatus
from app.exceptions import AuthorizationError
from app.middleware import limiter
from app.repositories.login_attempt_repository import LoginAttemptRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import APIResponse
from app.schemas.consent import ConsentInput, ConsentStatus
from app.schemas.group import PermissionsRead
from app.schemas.request import RequestRead
from app.schemas.user import (
    CreditPurchase,
    CreditRequest,
    CreditTransactionResult,
    PasswordChange,
    UserRead,
    UserUpdate,
)
from app.services.access import is_admin_user
from app.services.auth_cookie import clear_auth_cookies, set_auth_cookies
from app.services.consent_service import ConsentService
from app.services.group_service import GroupService
from app.services.login_throttle_service import LoginThrottleService
from app.services.request_service import RequestService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])
_repo = UserRepository()
_throttle = LoginThrottleService(LoginAttemptRepository())


def _get_service() -> UserService:
    return UserService(_repo, _throttle)


async def _refresh_session(svc: UserService, db: AsyncSession, response: Response, user_id) -> None:
    """After a password change the old token_version is dead; give this
    browser a fresh token so only *other* sessions are logged out."""
    set_auth_cookies(response, await svc.issue_access_token(db, user_id))


@router.get("/me", response_model=APIResponse[UserRead])
@limiter.limit("60/minute")
async def get_me(
    request: Request,
    current_user: UserRead = Depends(get_current_user),
):
    return APIResponse.ok(current_user)


@router.get("/me/permissions", response_model=APIResponse[PermissionsRead])
@limiter.limit("60/minute")
async def my_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Role, group memberships and consent state for menu/feature gating.
    The server still enforces every permission on each call."""
    groups = await GroupService().memberships(db, current_user.user_id)
    consent = await ConsentService().status(db, current_user.user_id)
    return APIResponse.ok(PermissionsRead(
        user_id=current_user.user_id,
        role=current_user.role,
        is_admin=is_admin_user(current_user),
        status=current_user.status,
        groups=groups,
        consent_up_to_date=consent.up_to_date,
    ))


@router.get("/me/consents", response_model=APIResponse[ConsentStatus])
@limiter.limit("60/minute")
async def my_consents(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    return APIResponse.ok(await ConsentService().status(db, current_user.user_id))


@router.post("/me/consents", response_model=APIResponse[ConsentStatus])
@limiter.limit("10/minute")
async def accept_consents(
    request: Request,
    body: ConsentInput,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Accept the current document versions (after a terms/privacy update)."""
    return APIResponse.ok(await ConsentService().accept_current(db, current_user.user_id, body))


@router.put("/me", response_model=APIResponse[UserRead])
@limiter.limit("30/minute")
async def update_me(
    request: Request,
    response: Response,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    updated = await svc.update(db, current_user.user_id, body)
    if body.user_password is not None:
        await _refresh_session(svc, db, response, current_user.user_id)
    return APIResponse.ok(updated)


@router.delete("/me", response_model=APIResponse[None])
@limiter.limit("10/minute")
async def delete_me(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    await svc.delete(db, current_user.user_id)
    clear_auth_cookies(response)
    return APIResponse.ok(None)


@router.post("/me/password", response_model=APIResponse[UserRead])
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    response: Response,
    body: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    updated = await svc.change_password(
        db, current_user.user_id, body.current_password, body.new_password
    )
    await _refresh_session(svc, db, response, current_user.user_id)
    return APIResponse.ok(updated)


@router.post(
    "/me/credits/purchase",
    response_model=APIResponse[CreditTransactionResult],
)
@limiter.limit("10/minute")
async def purchase_credits(
    request: Request,
    body: CreditPurchase,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Mock checkout: credits the account immediately (no payment provider).
    Disabled with CREDIT_PURCHASE_ENABLED=false."""
    if not settings.CREDIT_PURCHASE_ENABLED:
        raise AuthorizationError("Credit purchase is not available; submit a credit request instead")
    svc = _get_service()
    result = await svc.purchase_credits(db, current_user.user_id, body.quantity)
    return APIResponse.ok(result)


@router.post("/me/credit-request", response_model=APIResponse[RequestRead])
@limiter.limit("5/minute")
async def request_credits(
    request: Request,
    body: CreditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Queue a credit request. Small amounts may be granted automatically by
    policy; otherwise an administrator decides and the user is e-mailed."""
    result = await RequestService().submit_credit_request(
        db, current_user.user_id, body.requested_amount, body.reason
    )
    return APIResponse.ok(result)


@router.get("/me/requests", response_model=APIResponse[list[RequestRead]])
@limiter.limit("60/minute")
async def my_requests(
    request: Request,
    status: RequestStatus | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """The user's own requests (credits, sign-up) with their processing state."""
    items, meta = await RequestService().list_for_user(
        db, current_user.user_id, status.value if status else None, skip, limit
    )
    return APIResponse.ok(items, meta)
