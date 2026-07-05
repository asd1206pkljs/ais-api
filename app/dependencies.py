import uuid

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.exceptions import AuthenticationError
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserRead
from app.services.auth_service import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
_user_repo = UserRepository()

_INTERNAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def get_db() -> AsyncSession:  # ty:ignore[invalid-return-type]
    async for session in get_async_session():  # ty:ignore[not-iterable]  # pyright: ignore[reportGeneralTypeIssues]
        yield session


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    if token is None:
        raise AuthenticationError("Not authenticated")
    payload = decode_access_token(token)
    user_id_str = payload.get("sub")
    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, TypeError) as e:
        raise AuthenticationError("Invalid token subject") from e
    user = await _user_repo.find_by_id(db, user_id)
    if user is None:
        raise AuthenticationError("User not found")
    return UserRead.model_validate(user)


async def get_internal_or_user(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Internal API Key 또는 JWT 중 하나로 인증. user_id 반환."""
    if x_api_key and settings.INTERNAL_API_KEY and x_api_key == settings.INTERNAL_API_KEY:
        return _INTERNAL_USER_ID

    if token is None:
        raise AuthenticationError("Not authenticated")
    payload = decode_access_token(token)
    user_id_str = payload.get("sub")
    try:
        return uuid.UUID(user_id_str)
    except (ValueError, TypeError) as e:
        raise AuthenticationError("Invalid token subject") from e


async def require_internal(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> None:
    """Internal API Key 전용 엔드포인트 보호."""
    if not settings.INTERNAL_API_KEY:
        raise AuthenticationError("Internal API key not configured")
    if x_api_key != settings.INTERNAL_API_KEY:
        raise AuthenticationError("Invalid internal API key")
