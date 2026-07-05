import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ModuleType
from app.models.module import Module
from app.repositories.base import BaseRepository


class ModuleRepository(BaseRepository[Module]):
    def __init__(self):
        super().__init__(Module)

    async def find_by_id(self, session: AsyncSession, entity_id) -> Module | None:
        result = await session.execute(select(Module).where(Module.module_id == entity_id))
        return result.scalar_one_or_none()

    async def find_by_type(
        self, session: AsyncSession, module_type: ModuleType, skip: int = 0, limit: int = 100
    ) -> list[Module]:
        result = await session.execute(
            select(Module).where(Module.module_type == module_type).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def sync_equipment_link(
        self, session: AsyncSession, equipment_id: uuid.UUID, module_ids: list[int]
    ) -> None:
        """config에 있는 module들은 equipment_id를 연결하고, 제거된 module들은 NULL로 해제."""
        if module_ids:
            await session.execute(
                update(Module)
                .where(Module.module_id.in_(module_ids))
                .values(equipment_id=equipment_id)
            )
        await session.execute(
            update(Module)
            .where(
                Module.equipment_id == equipment_id,
                Module.module_id.not_in(module_ids) if module_ids else Module.module_id.is_not(None),
            )
            .values(equipment_id=None)
        )
        await session.commit()
