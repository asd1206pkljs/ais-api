import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self):
        super().__init__(User)

    async def find_by_id(self, session: AsyncSession, entity_id) -> User | None:
        result = await session.execute(select(User).where(User.user_id == entity_id))
        return result.scalar_one_or_none()

    async def find_by_email(self, session: AsyncSession, email: str) -> User | None:
        """Return the approved (verified) account for this email, if any.

        Unverified sign-ups are excluded — see find_pending_by_email. At most
        one approved row exists per email (partial unique index).
        """
        result = await session.execute(
            select(User).where(User.user_email == email, User.approved.is_(True))
        )
        return result.scalar_one_or_none()

    async def find_pending_by_email(self, session: AsyncSession, email: str) -> list[User]:
        """Return unverified sign-ups for this email, newest first."""
        result = await session.execute(
            select(User)
            .where(User.user_email == email, User.approved.is_(False))
            .order_by(User.joined_at.desc())
        )
        return list(result.scalars().all())

    async def delete_pending_by_email(
        self, session: AsyncSession, email: str, *, exclude_user_id: uuid.UUID
    ) -> int:
        """Delete unverified sign-ups for this email other than `exclude_user_id`.

        Caller is responsible for commit/rollback.
        """
        result = await session.execute(
            delete(User).where(
                User.user_email == email,
                User.approved.is_(False),
                User.user_id != exclude_user_id,
            )
        )
        return result.rowcount

    async def delete_stale_pending(self, session: AsyncSession, before: datetime) -> int:
        """Delete unverified sign-ups created before `before`. Caller commits."""
        result = await session.execute(
            delete(User).where(User.approved.is_(False), User.joined_at < before)
        )
        return result.rowcount

    async def try_deduct_credit(
        self, session: AsyncSession, user_id: uuid.UUID, amount: int = 1
    ) -> bool:
        """Atomically deduct `amount` credits if the user has enough.

        Returns True if deduction succeeded, False if insufficient balance.
        Caller is responsible for commit/rollback.
        """
        result = await session.execute(
            update(User)
            .where(User.user_id == user_id, User.user_credits >= amount)
            .values(user_credits=User.user_credits - amount)
        )
        return result.rowcount > 0

    async def refund_credit(
        self, session: AsyncSession, user_id: uuid.UUID, amount: int = 1
    ) -> None:
        """Atomically increment credits. Caller is responsible for commit/rollback."""
        await session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(user_credits=User.user_credits + amount)
        )
