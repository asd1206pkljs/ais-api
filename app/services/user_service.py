import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SharePrincipalType, UserStatus
from app.enums import audit_action as act
from app.exceptions import (
    AccountDisabledError,
    AccountPendingApprovalError,
    AuthenticationError,
    ConflictError,
    EmailNotVerifiedError,
    NotFoundError,
)
from app.models.user import User
from app.repositories.resource_share_repository import ResourceShareRepository
from app.repositories.user_repository import UserRepository
from app.schemas.consent import ConsentInput
from app.schemas.user import (
    CreditTransactionResult,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.auth_service import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.services.audit_context import Actor
from app.services.audit_service import AuditService, audit
from app.services.consent_service import ConsentService
from app.services.login_throttle_service import LoginThrottleService


CREDIT_PRICE_KRW = 500_000


def _password_matches(user: User | None, password: str) -> bool:
    """Credential check that costs one bcrypt round whether or not the account exists,
    so response time cannot be used to discover which emails are registered."""
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return False
    return verify_password(password, user.user_password)


class UserService:
    def __init__(
        self,
        repo: UserRepository,
        throttle: LoginThrottleService,
        consents: ConsentService | None = None,
        audit_svc: AuditService = audit,
        share_repo: ResourceShareRepository | None = None,
    ):
        self._repo = repo
        self._throttle = throttle
        self._consents = consents or ConsentService()
        self._audit = audit_svc
        self._shares = share_repo or ResourceShareRepository()

    async def register(
        self, session: AsyncSession, data: UserCreate, consents: ConsentInput | None = None
    ) -> UserRead:
        """Create an unverified account and record the accepted legal documents.

        Only an *approved* account blocks re-registration. Unverified sign-ups
        for the same email are allowed so someone else's pending registration
        can never lock the real owner out; they are cleaned up on verification.
        """
        accepted = self._consents.validate_registration(consents)
        existing = await self._repo.find_by_email(session, data.user_email)
        if existing is not None:
            raise ConflictError("Email already registered")
        user = await self._repo.create(session, {
            "user_name": data.user_name,
            "user_email": data.user_email,
            "user_password": hash_password(data.user_password),
            "user_company": data.user_company,
            "approved": False,
            "status": UserStatus.PENDING_APPROVAL.value,
        })
        await self._consents.record(session, user.user_id, accepted)
        await session.commit()
        actor = Actor(user_id=user.user_id, email=user.user_email, actor_type="user")
        await self._audit.record(session, act.REGISTER, target_user_id=user.user_id, actor=actor)
        if accepted is not None:
            await self._audit.record(session, act.CONSENT_ACCEPTED, target_user_id=user.user_id,
                                     actor=actor, details=accepted.model_dump())
        return UserRead.model_validate(user)

    @staticmethod
    def _require_active(user: User) -> None:
        if user.status == UserStatus.DISABLED.value:
            raise AccountDisabledError()
        if user.status != UserStatus.ACTIVE.value:
            raise AccountPendingApprovalError()

    async def authenticate(self, session: AsyncSession, email: str, password: str) -> UserRead:
        """Verify credentials against the verified account for `email`.

        Raises AccountLockedError while the email is locked out, EmailNotVerifiedError
        when the credentials match a pending sign-up, otherwise AuthenticationError.
        """
        await self._throttle.check_not_locked(session, email)
        user = await self._repo.find_by_email(session, email)
        if _password_matches(user, password):
            self._require_active(user)
            await self._throttle.clear(session, email)
            logged_in = await self._record_login(session, user)
            await self._audit.record(
                session, act.LOGIN_SUCCESS, target_user_id=user.user_id,
                actor=Actor(user_id=user.user_id, email=user.user_email, actor_type="user"),
            )
            return logged_in
        await self._audit.record(session, act.LOGIN_FAILURE, outcome="failure",
                                 details={"email": email})
        # Counts toward lockout; raises AccountLockedError if this attempt tripped it.
        await self._throttle.record_failure(session, email)
        # Only reveal "not verified" to someone who proves they own a pending
        # sign-up (correct password); otherwise stay generic so this endpoint
        # cannot be used to discover which emails are registered.
        if await self._matches_pending(session, email, password):
            raise EmailNotVerifiedError()
        raise AuthenticationError("Invalid email or password")

    async def issue_access_token(self, session: AsyncSession, user_id: uuid.UUID) -> str:
        """Mint an access token bound to the user's current token_version."""
        user = await self._repo.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return create_access_token(user.user_id, user.user_email, user.token_version)

    async def _record_login(self, session: AsyncSession, user: User) -> UserRead:
        await self._repo.update(
            session, user.user_id, {"last_login_at": datetime.now(timezone.utc)}
        )
        updated = await self._repo.find_by_id(session, user.user_id)
        return UserRead.model_validate(updated)

    async def _matches_pending(self, session: AsyncSession, email: str, password: str) -> bool:
        pending = await self._repo.find_pending_by_email(session, email)
        return any(verify_password(password, p.user_password) for p in pending)

    async def get_by_id(self, session: AsyncSession, user_id: uuid.UUID) -> UserRead:
        user = await self._repo.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return UserRead.model_validate(user)

    async def update(
        self, session: AsyncSession, user_id: uuid.UUID, data: UserUpdate
    ) -> UserRead:
        update_data = data.model_dump(exclude_none=True)
        if "user_password" in update_data:
            user = await self._repo.find_by_id(session, user_id)
            if user is None:
                raise NotFoundError("User", str(user_id))
            update_data["user_password"] = hash_password(update_data["user_password"])
            # A new password ends every session started with the old one.
            update_data["token_version"] = user.token_version + 1
        updated = await self._repo.update(session, user_id, update_data)
        if updated is None:
            raise NotFoundError("User", str(user_id))
        await self._audit.record(
            session, act.PASSWORD_CHANGED if "user_password" in update_data else act.ACCOUNT_UPDATED,
            target_user_id=user_id,
            details={k: v for k, v in update_data.items() if k not in ("user_password", "token_version")},
        )
        return UserRead.model_validate(updated)

    async def delete(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        """Delete the account. Owned resources cascade in the database; grants
        made *to* this user are removed explicitly (no FK on principal_id)."""
        await self._shares.delete_for_principal(session, SharePrincipalType.USER.value, str(user_id))
        await self._shares.delete_for_resources_owned_by(session, user_id)
        deleted = await self._repo.delete(session, user_id)
        if not deleted:
            raise NotFoundError("User", str(user_id))
        await self._audit.record(session, act.ACCOUNT_DELETED, target_user_id=user_id)

    async def change_password(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
    ) -> UserRead:
        user = await self._repo.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        if not verify_password(current_password, user.user_password):
            raise AuthenticationError("Current password is incorrect")
        updated = await self._repo.update(session, user_id, {
            "user_password": hash_password(new_password),
            # Invalidate every other session that was using the old password.
            "token_version": user.token_version + 1,
        })
        if updated is None:
            raise NotFoundError("User", str(user_id))
        await self._audit.record(session, act.PASSWORD_CHANGED, target_user_id=user_id)
        return UserRead.model_validate(updated)

    async def purchase_credits(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        quantity: int,
    ) -> CreditTransactionResult:
        await self._repo.refund_credit(session, user_id, quantity)
        await session.commit()
        updated = await self._repo.find_by_id(session, user_id)
        if updated is None:
            raise NotFoundError("User", str(user_id))
        await self._audit.record(session, act.CREDITS_PURCHASED, target_user_id=user_id,
                                 details={"quantity": quantity, "total_paid_krw": quantity * CREDIT_PRICE_KRW})
        return CreditTransactionResult(
            user_credits=updated.user_credits,
            added=quantity,
            total_paid_krw=quantity * CREDIT_PRICE_KRW,
        )
