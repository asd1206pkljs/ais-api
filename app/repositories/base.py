from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: type[ModelType]):
        self._model = model

    async def find_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> list[ModelType]:
        result = await session.execute(select(self._model).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def find_by_id(self, session: AsyncSession, entity_id: Any) -> ModelType | None:
        result = await session.execute(
            select(self._model).where(self._model.__mapper__.primary_key[0] == entity_id)
        )
        return result.scalar_one_or_none()

    async def count(self, session: AsyncSession) -> int:
        result = await session.execute(select(func.count()).select_from(self._model))
        return result.scalar_one()

    async def create(self, session: AsyncSession, data: dict) -> ModelType:
        instance = self._model(**data)
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
        return instance

    async def update(self, session: AsyncSession, entity_id: Any, data: dict) -> ModelType | None:
        instance = await self.find_by_id(session, entity_id)
        if instance is None:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        await session.commit()
        await session.refresh(instance)
        return instance

    async def delete(self, session: AsyncSession, entity_id: Any) -> bool:
        instance = await self.find_by_id(session, entity_id)
        if instance is None:
            return False
        await session.delete(instance)
        await session.commit()
        return True
