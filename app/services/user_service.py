import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    AuthenticationError,
    ConflictError,
    EmailNotVerifiedError,
    NotFoundError,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
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
    def __init__(self, repo: UserRepository, throttle: LoginThrottleService):
        self._repo = repo
        self._throttle = throttle

    async def register(self, session: AsyncSession, data: UserCreate) -> UserRead:
        """Create an unverified account.

        Only an *approved* account blocks re-registration. Unverified sign-ups
        for the same email are allowed so someone else's pending registration
        can never lock the real owner out; they are cleaned up on verification.
        """
        existing = await self._repo.find_by_email(session, data.user_email)
        if existing is not None:
            raise ConflictError("Email already registered")
        user = await self._repo.create(session, {
            "user_name": data.user_name,
            "user_email": data.user_email,
            "user_password": hash_password(data.user_password),
            "user_company": data.user_company,
            "approved": False,
        })
        return UserRead.model_validate(user)

    async def authenticate(self, session: AsyncSession, email: str, password: str) -> UserRead:
        """Verify credentials against the verified account for `email`.

        Raises AccountLockedError while the email is locked out, EmailNotVerifiedError
        when the credentials match a pending sign-up, otherwise AuthenticationError.
        """
        await self._throttle.check_not_locked(session, email)
        user = await self._repo.find_by_email(session, email)
        if _password_matches(user, password):
            await self._throttle.clear(session, email)
            return await self._record_login(session, user)
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
        return UserRead.model_validate(updated)

    async def delete(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        deleted = await self._repo.delete(session, user_id)
        if not deleted:
            raise NotFoundError("User", str(user_id))

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
        return CreditTransactionResult(
            user_credits=updated.user_credits,
            added=quantity,
            total_paid_krw=quantity * CREDIT_PRICE_KRW,
        )
