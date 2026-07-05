import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import NotFoundError, ValidationError
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password
from app.services.email_service import send_password_reset_email

PURPOSE = "pwd_reset"
PWD_PREFIX_LEN = 16


def _password_prefix(password_hash: str) -> str:
    return password_hash[:PWD_PREFIX_LEN]


def _build_reset_url(token: str) -> str:
    base = settings.PASSWORD_RESET_URL_BASE.rstrip("/")
    return f"{base}/reset-password?token={quote(token, safe='')}"


def _issue_token(user_id: uuid.UUID, password_hash: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TTL_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "purpose": PURPOSE,
        "pwd_prefix": _password_prefix(password_hash),
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


class EmailNotRegisteredError(NotFoundError):
    """Raised when password-reset is requested for an unknown email."""

    def __init__(self):
        # Skip parent's auto-formatted message; use a stable code-friendly string.
        Exception.__init__(self, "Email not registered")
        self.resource = "User"
        self.resource_id = ""


class PasswordResetService:
    def __init__(self, repo: UserRepository):
        self._repo = repo

    async def request_reset(self, session: AsyncSession, email: str) -> None:
        """Send a password-reset link to the email.

        Raises EmailNotRegisteredError if no account exists for the email.
        """
        user = await self._repo.find_by_email(session, email)
        if user is None:
            raise EmailNotRegisteredError()
        token = _issue_token(user.user_id, user.user_password)
        reset_url = _build_reset_url(token)
        send_password_reset_email(user.user_email, reset_url)

    async def consume_token(
        self, session: AsyncSession, token: str, new_password: str
    ) -> None:
        """Validate the reset token and update the user's password.

        Raises ValidationError on any failure (expired, malformed, already used,
        or password already changed since the link was issued).
        """
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            raise ValidationError("Invalid or expired reset link")

        if payload.get("purpose") != PURPOSE:
            raise ValidationError("Invalid or expired reset link")

        sub = payload.get("sub")
        prefix = payload.get("pwd_prefix")
        if not sub or not prefix:
            raise ValidationError("Invalid or expired reset link")

        try:
            user_id = uuid.UUID(sub)
        except ValueError:
            raise ValidationError("Invalid or expired reset link")

        user = await self._repo.find_by_id(session, user_id)
        if user is None:
            raise ValidationError("Invalid or expired reset link")
        if _password_prefix(user.user_password) != prefix:
            # Password was already changed — token is stale.
            raise ValidationError("Invalid or expired reset link")

        await self._repo.update(
            session, user_id, {"user_password": hash_password(new_password)}
        )
