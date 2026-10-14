import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ConflictError, ValidationError
from app.models.user import User
from app.enums import audit_action as act
from app.repositories.user_repository import UserRepository
from app.services.activation_service import ActivationService
from app.services.audit_context import Actor
from app.services.audit_service import AuditService, audit
from app.services.email_service import send_verification_email

PURPOSE = "email_verify"
INVALID_LINK = "Invalid or expired verification link"
ALREADY_VERIFIED_ELSEWHERE = "This email has already been verified by another account"


def _build_verify_url(token: str) -> str:
    base = settings.email_verify_url_base.rstrip("/")
    return f"{base}/verify-email?token={quote(token, safe='')}"


def _issue_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFY_TTL_HOURS)
    payload = {"sub": str(user_id), "purpose": PURPOSE, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise ValidationError(INVALID_LINK)
    if payload.get("purpose") != PURPOSE:
        raise ValidationError(INVALID_LINK)
    try:
        return uuid.UUID(payload.get("sub") or "")
    except ValueError:
        raise ValidationError(INVALID_LINK)


class EmailVerificationService:
    def __init__(
        self,
        repo: UserRepository,
        activation: ActivationService | None = None,
        audit_svc: AuditService = audit,
    ):
        self._repo = repo
        self._activation = activation or ActivationService(user_repo=repo, audit_svc=audit_svc)
        self._audit = audit_svc

    def send(self, user_id: uuid.UUID, email: str) -> None:
        """Email a verification link for a pending sign-up."""
        send_verification_email(email, _build_verify_url(_issue_token(user_id)))

    async def resend(self, session: AsyncSession, email: str) -> None:
        """Re-send the link to the newest pending sign-up for `email`.

        Does nothing when the email is already verified or has no pending
        sign-up, so the endpoint cannot be used to enumerate accounts.
        """
        if await self._repo.find_by_email(session, email) is not None:
            return
        pending = await self._repo.find_pending_by_email(session, email)
        if pending:
            self.send(pending[0].user_id, pending[0].user_email)

    async def consume_token(self, session: AsyncSession, token: str) -> None:
        """Mark the sign-up referenced by `token` as approved.

        Idempotent for an already-approved account. Other pending sign-ups for
        the same email are removed once one is verified; if a different
        account already verified this email, this one is discarded instead.
        """
        user_id = _decode_token(token)
        user = await self._repo.find_by_id(session, user_id)
        if user is None:
            raise ValidationError(INVALID_LINK)
        if user.approved:
            return
        await self._approve(session, user)
        actor = Actor(user_id=user.user_id, email=user.user_email, actor_type="user")
        await self._audit.record(session, act.EMAIL_VERIFIED, target_user_id=user.user_id, actor=actor)
        # Verified ≠ allowed in: apply the sign-up approval policy.
        await self._activation.on_email_verified(session, user)

    async def _approve(self, session: AsyncSession, user: User) -> None:
        if await self._repo.find_by_email(session, user.user_email) is not None:
            await self._repo.delete(session, user.user_id)
            raise ConflictError(ALREADY_VERIFIED_ELSEWHERE)
        try:
            await self._repo.update(session, user.user_id, {"approved": True})
        except IntegrityError:
            # Lost a race with a concurrent verification of the same email;
            # the partial unique index rejected this row.
            await session.rollback()
            await self._repo.delete(session, user.user_id)
            raise ConflictError(ALREADY_VERIFIED_ELSEWHERE)
        await self._repo.delete_pending_by_email(
            session, user.user_email, exclude_user_id=user.user_id
        )
        await session.commit()
