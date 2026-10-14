import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.simulator import Simulator
from app.repositories.access_filters import shared_with
from app.repositories.base import BaseRepository


class SimulatorRepository(BaseRepository[Simulator]):
    def __init__(self):
        super().__init__(Simulator)

    async def find_by_id(self, session: AsyncSession, entity_id) -> Simulator | None:
        result = await session.execute(
            select(Simulator).where(Simulator.simulator_id == entity_id)
        )
        return result.scalar_one_or_none()

    async def find_by_owner(
        self, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Simulator]:
        result = await session.execute(
            select(Simulator)
            .where(Simulator.owner_id == owner_id, Simulator.save_status != 'deleted')
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_accessible_by_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        principals: list[str],
        skip: int = 0,
        limit: int = 100,
    ) -> list[Simulator]:
        """Owned by the user or shared with one of `principals` (user, groups, public)."""
        result = await session.execute(
            select(Simulator)
            .where(
                Simulator.save_status != 'deleted',
                (Simulator.owner_id == user_id)
                | shared_with(Simulator.simulator_id, "simulator", principals),
            )
            .order_by(Simulator.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> list[Simulator]:
        result = await session.execute(
            select(Simulator)
            .where(Simulator.save_status != 'deleted')
            .order_by(Simulator.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_equipment(
        self, session: AsyncSession, equipment_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[Simulator]:
        result = await session.execute(
            select(Simulator).where(
                Simulator.equipment_id == equipment_id,
                Simulator.owner_id == owner_id,
            )
        )
        return list(result.scalars().all())
