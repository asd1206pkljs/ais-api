import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.repositories.access_filters import shared_with
from app.repositories.base import BaseRepository


class EquipmentRepository(BaseRepository[Equipment]):
    def __init__(self):
        super().__init__(Equipment)

    async def find_by_id(self, session: AsyncSession, entity_id) -> Equipment | None:
        result = await session.execute(
            select(Equipment).where(Equipment.equipment_id == entity_id)
        )
        return result.scalar_one_or_none()

    async def find_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> list[Equipment]:
        # admin 목록 조회 경로. soft-delete(save_status == 'deleted') 된 장비는 제외한다.
        result = await session.execute(
            select(Equipment)
            .where(Equipment.save_status != 'deleted')
            .order_by(Equipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_owner(
        self, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Equipment]:
        result = await session.execute(
            select(Equipment)
            .where(Equipment.owner_id == owner_id, Equipment.save_status != 'deleted')
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    def _accessible_filter(self, user_id: uuid.UUID, principals: list[str]):
        return (
            Equipment.save_status != 'deleted',
            (Equipment.owner_id == user_id)
            | shared_with(Equipment.equipment_id, "equipment", principals),
        )

    async def find_accessible_by_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        principals: list[str],
        skip: int = 0,
        limit: int = 100,
    ) -> list[Equipment]:
        """Owned by the user or shared with one of `principals` (user, groups, public)."""
        result = await session.execute(
            select(Equipment)
            .where(*self._accessible_filter(user_id, principals))
            .order_by(Equipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_accessible_by_user(
        self, session: AsyncSession, user_id: uuid.UUID, principals: list[str]
    ) -> int:
        result = await session.execute(
            select(func.count()).select_from(Equipment).where(*self._accessible_filter(user_id, principals))
        )
        return result.scalar_one()
