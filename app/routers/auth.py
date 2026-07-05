from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.middleware import limiter
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import APIResponse
from app.schemas.password_reset import (
    ForgotPasswordRequest,
    MessageResponse,
    ResetPasswordRequest,
)
from app.services.auth_service import create_access_token
from app.services.password_reset_service import PasswordResetService
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])
_repo = UserRepository()


def _get_service() -> UserService:
    return UserService(_repo)


def _get_password_reset_service() -> PasswordResetService:
    return PasswordResetService(_repo)


@router.post("/register", response_model=APIResponse[TokenResponse])
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = _get_service()
    from app.schemas.user import UserCreate
    user = await svc.register(db, UserCreate(
        user_name=body.user_name,
        user_email=body.email,
        user_password=body.password,
        user_company=body.company,
    ))
    token = create_access_token(user.user_id, user.user_email)
    return APIResponse.ok(TokenResponse(access_token=token))


@router.post("/login", response_model=APIResponse[TokenResponse])
@limiter.limit("20/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = _get_service()
    user = await svc.authenticate(db, body.email, body.password)
    token = create_access_token(user.user_id, user.user_email)
    return APIResponse.ok(TokenResponse(access_token=token))


@router.post("/forgot-password", response_model=APIResponse[MessageResponse])
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = _get_password_reset_service()
    await svc.request_reset(db, body.email)
    return APIResponse.ok(MessageResponse(message="Password reset email sent"))


@router.post("/reset-password", response_model=APIResponse[MessageResponse])
@limiter.limit("10/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = _get_password_reset_service()
    await svc.consume_token(db, body.token, body.new_password)
    return APIResponse.ok(MessageResponse(message="Password updated"))
