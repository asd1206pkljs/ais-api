import uuid

from sqlalchemy import select, update
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
        result = await session.execute(select(User).where(User.user_email == email))
        return result.scalar_one_or_none()

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
