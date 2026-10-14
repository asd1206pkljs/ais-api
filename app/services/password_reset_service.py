import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ValidationError
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password
from app.enums import audit_action as act
from app.services.audit_context import Actor
from app.services.audit_service import AuditService, audit
from app.services.email_service import send_password_reset_email
from app.services.login_throttle_service import LoginThrottleService

logger = logging.getLogger(__name__)

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


class PasswordResetService:
    def __init__(
        self, repo: UserRepository, throttle: LoginThrottleService, audit_svc: AuditService = audit
    ):
        self._repo = repo
        self._throttle = throttle
        self._audit = audit_svc

    async def request_reset(self, session: AsyncSession, email: str) -> None:
        """Send a password-reset link if a verified account exists for `email`.

        Silently does nothing otherwise (unknown or unverified email) so the
        endpoint cannot be used to discover which emails are registered.
        """
        user = await self._repo.find_by_email(session, email)
        if user is None:
            logger.info("Password reset requested for unknown/unverified email")
            return
        token = _issue_token(user.user_id, user.user_password)
        send_password_reset_email(user.user_email, _build_reset_url(token))
        await self._audit.record(session, act.PASSWORD_RESET_REQUESTED, target_user_id=user.user_id)

    async def consume_token(
        self, session: AsyncSession, token: str, new_password: str
    ) -> None:
        """Validate the reset token and set the new password.

        Also invalidates every outstanding access token (token_version bump)
        and clears any login lockout, so the legitimate owner regains access.
        Raises ValidationError on any failure (expired, malformed, already used,
        or password already changed since the link was issued).
        """
        user_id, prefix = self._decode(token)
        user = await self._repo.find_by_id(session, user_id)
        if user is None or _password_prefix(user.user_password) != prefix:
            # Unknown user, or password already changed — token is stale.
            raise ValidationError("Invalid or expired reset link")

        await self._repo.update(session, user_id, {
            "user_password": hash_password(new_password),
            "token_version": user.token_version + 1,
        })
        await self._throttle.clear(session, user.user_email)
        await self._audit.record(
            session, act.PASSWORD_RESET, target_user_id=user_id,
            actor=Actor(user_id=user.user_id, email=user.user_email, actor_type="user"),
        )

    @staticmethod
    def _decode(token: str) -> tuple[uuid.UUID, str]:
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
        except JWTError:
            raise ValidationError("Invalid or expired reset link")
        sub, prefix = payload.get("sub"), payload.get("pwd_prefix")
        if payload.get("purpose") != PURPOSE or not sub or not prefix:
            raise ValidationError("Invalid or expired reset link")
        try:
            return uuid.UUID(sub), prefix
        except ValueError:
            raise ValidationError("Invalid or expired reset link")
