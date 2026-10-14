import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import extract_access_token, get_db, oauth2_scheme
from app.exceptions import AuthenticationError
from app.middleware import limiter
from app.repositories.login_attempt_repository import LoginAttemptRepository
from app.repositories.revoked_token_repository import RevokedTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.schemas.common import APIResponse
from app.schemas.password_reset import (
    ForgotPasswordRequest,
    MessageResponse,
    ResetPasswordRequest,
)
from app.schemas.user import UserCreate
from app.services.auth_cookie import clear_auth_cookies, set_auth_cookies
from app.services.auth_service import decode_access_token
from app.services.email_verification_service import EmailVerificationService
from app.services.login_throttle_service import LoginThrottleService
from app.services.password_reset_service import PasswordResetService
from app.services.token_revocation_service import TokenRevocationService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
_repo = UserRepository()
_throttle = LoginThrottleService(LoginAttemptRepository())
_revocations = TokenRevocationService(RevokedTokenRepository())


def _get_service() -> UserService:
    return UserService(_repo, _throttle)


def _get_password_reset_service() -> PasswordResetService:
    return PasswordResetService(_repo, _throttle)


def _get_verification_service() -> EmailVerificationService:
    return EmailVerificationService(_repo)


@router.post("/register", response_model=APIResponse[MessageResponse])
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create an unverified account and email a verification link.

    No session is started here — the user must click the link, then log in.
    """
    svc = _get_service()
    user = await svc.register(db, UserCreate(
        user_name=body.user_name,
        user_email=body.email,
        user_password=body.password,
        user_company=body.company,
    ))
    try:
        _get_verification_service().send(user.user_id, user.user_email)
    except Exception:
        # Don't leave behind a pending account that can never be verified.
        logger.exception("Failed to send verification email to %s", user.user_email)
        await svc.delete(db, user.user_id)
        raise
    return APIResponse.ok(MessageResponse(message="Verification email sent"))


@router.post("/verify-email", response_model=APIResponse[MessageResponse])
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_verification_service().consume_token(db, body.token)
    return APIResponse.ok(MessageResponse(message="Email verified"))


@router.post("/resend-verification", response_model=APIResponse[MessageResponse])
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_verification_service().resend(db, body.email)
    # Same reply whether or not a pending sign-up exists (no enumeration).
    return APIResponse.ok(MessageResponse(
        message="If a pending sign-up exists for this email, a verification email has been sent"
    ))


@router.post("/login", response_model=APIResponse[TokenResponse])
@limiter.limit("20/minute")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and start a session.

    The token is set as an HttpOnly cookie (what the web app relies on) and is
    also returned in the body for non-browser API clients that send it as a
    Bearer header. The web app never stores the body copy.
    """
    svc = _get_service()
    user = await svc.authenticate(db, body.email, body.password)
    token = await svc.issue_access_token(db, user.user_id)
    set_auth_cookies(response, token)
    return APIResponse.ok(TokenResponse(access_token=token))


@router.post("/logout", response_model=APIResponse[MessageResponse])
@limiter.limit("30/minute")
async def logout(
    request: Request,
    response: Response,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """End the session: revoke the current token (if still valid) and clear cookies.

    Always succeeds so a client holding an expired or malformed cookie can still
    clean up.
    """
    raw = extract_access_token(request, token)
    if raw is not None:
        try:
            payload = decode_access_token(raw)
        except AuthenticationError:
            payload = None  # expired or malformed — nothing left to revoke
        if payload is not None:
            await _revocations.revoke(db, payload)
    clear_auth_cookies(response)
    return APIResponse.ok(MessageResponse(message="Logged out"))


@router.post("/forgot-password", response_model=APIResponse[MessageResponse])
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_password_reset_service().request_reset(db, body.email)
    # Same reply whether or not the email is registered (no enumeration).
    return APIResponse.ok(MessageResponse(
        message="If an account exists for this email, a password reset link has been sent"
    ))


@router.post("/reset-password", response_model=APIResponse[MessageResponse])
@limiter.limit("10/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_password_reset_service().consume_token(db, body.token, body.new_password)
    return APIResponse.ok(MessageResponse(message="Password updated"))
