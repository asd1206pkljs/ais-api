from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.middleware import limiter
from app.repositories.login_attempt_repository import LoginAttemptRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import APIResponse
from app.schemas.user import (
    CreditPurchase,
    CreditRequest,
    CreditTransactionResult,
    PasswordChange,
    UserRead,
    UserUpdate,
)
from app.services.auth_cookie import clear_auth_cookies, set_auth_cookies
from app.services.login_throttle_service import LoginThrottleService
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
    svc = _get_service()
    result = await svc.purchase_credits(db, current_user.user_id, body.quantity)
    return APIResponse.ok(result)


@router.post("/me/credit-request", response_model=APIResponse[None])
@limiter.limit("5/minute")
async def request_credits(
    request: Request,
    body: CreditRequest,
    current_user: UserRead = Depends(get_current_user),
):
    # Placeholder: a real implementation would notify an administrator
    # via email/queue. For now we accept the request and rely on operator
    # follow-up out-of-band.
    _ = (body, current_user)
    return APIResponse.ok(None)
