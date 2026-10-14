import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
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
        # (base.find_all 은 필터가 없어, 오버라이드하지 않으면 admin 에게 삭제 장비가 되살아난다)
        result = await session.execute(
            select(Equipment)
            .where(Equipment.save_status != 'deleted')
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

    async def find_accessible_by_user(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Equipment]:
        uid_str = str(user_id)
        result = await session.execute(
            select(Equipment)
            .where(
                Equipment.save_status != 'deleted',
                or_(
                    Equipment.owner_id == user_id,
                    Equipment.viewers.contains([uid_str]),
                    Equipment.editors.contains([uid_str]),
                    Equipment.viewers.contains(["*"]),
                    Equipment.editors.contains(["*"]),
                ),
            )
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
