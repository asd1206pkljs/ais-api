import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    CreditTransactionResult,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.auth_service import hash_password, verify_password


CREDIT_PRICE_KRW = 500_000


class UserService:
    def __init__(self, repo: UserRepository):
        self._repo = repo

    async def register(self, session: AsyncSession, data: UserCreate) -> UserRead:
        existing = await self._repo.find_by_email(session, data.user_email)
        if existing is not None:
            raise ConflictError(f"Email '{data.user_email}' is already registered")
        user = await self._repo.create(session, {
            "user_name": data.user_name,
            "user_email": data.user_email,
            "user_password": hash_password(data.user_password),
        })
        return UserRead.model_validate(user)

    async def authenticate(self, session: AsyncSession, email: str, password: str) -> UserRead:
        user = await self._repo.find_by_email(session, email)
        if user is None or not verify_password(password, user.user_password):
            raise AuthenticationError("Invalid email or password")
        await self._repo.update(
            session, user.user_id, {"last_login_at": datetime.now(timezone.utc)}
        )
        updated = await self._repo.find_by_id(session, user.user_id)
        return UserRead.model_validate(updated)

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
            update_data["user_password"] = hash_password(update_data["user_password"])
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
        updated = await self._repo.update(
            session, user_id, {"user_password": hash_password(new_password)}
        )
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
