import uuid

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.exceptions import AuthenticationError
from app.models.user import User
from app.repositories.revoked_token_repository import RevokedTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserRead
from app.services.auth_service import decode_access_token
from app.services.token_revocation_service import TokenRevocationService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
_user_repo = UserRepository()
_revocations = TokenRevocationService(RevokedTokenRepository())

_INTERNAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def get_db() -> AsyncSession:  # ty:ignore[invalid-return-type]
    async for session in get_async_session():  # ty:ignore[not-iterable]  # pyright: ignore[reportGeneralTypeIssues]
        yield session


def extract_access_token(request: Request, bearer: str | None) -> str | None:
    """Browser sessions carry the token in an HttpOnly cookie; API clients may
    send it as a Bearer header instead. The header wins when both are present."""
    return bearer or request.cookies.get(settings.AUTH_COOKIE_NAME)


async def authenticate_token(token: str, db: AsyncSession) -> User:
    """Validate an access token end to end: signature and expiry, not revoked,
    user still exists, email verified, and not issued before a password change."""
    payload = decode_access_token(token)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError) as e:
        raise AuthenticationError("Invalid token subject") from e
    if await _revocations.is_revoked(db, payload["jti"]):
        raise AuthenticationError("Token has been revoked")
    user = await _user_repo.find_by_id(db, user_id)
    if user is None:
        raise AuthenticationError("User not found")
    if not user.approved:
        raise AuthenticationError("Email not verified")
    if payload["ver"] != user.token_version:
        raise AuthenticationError("Session is no longer valid")
    return user


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    raw = extract_access_token(request, token)
    if raw is None:
        raise AuthenticationError("Not authenticated")
    return UserRead.model_validate(await authenticate_token(raw, db))


async def get_internal_or_user(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Internal API Key 또는 JWT 중 하나로 인증. user_id 반환."""
    if x_api_key and settings.INTERNAL_API_KEY and x_api_key == settings.INTERNAL_API_KEY:
        return _INTERNAL_USER_ID

    raw = extract_access_token(request, token)
    if raw is None:
        raise AuthenticationError("Not authenticated")
    return (await authenticate_token(raw, db)).user_id


async def require_internal(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> None:
    """Internal API Key 전용 엔드포인트 보호."""
    if not settings.INTERNAL_API_KEY:
        raise AuthenticationError("Internal API key not configured")
    if x_api_key != settings.INTERNAL_API_KEY:
        raise AuthenticationError("Invalid internal API key")
