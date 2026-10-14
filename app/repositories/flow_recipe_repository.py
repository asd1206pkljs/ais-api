import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow_recipe import FlowRecipe
from app.repositories.access_filters import accessible_equipment_ids, shared_with
from app.repositories.base import BaseRepository


class FlowRecipeRepository(BaseRepository[FlowRecipe]):
    def __init__(self):
        super().__init__(FlowRecipe)

    async def find_by_id(self, session: AsyncSession, entity_id) -> FlowRecipe | None:
        result = await session.execute(
            select(FlowRecipe).where(FlowRecipe.flow_recipe_id == entity_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _accessible_filter(user_id: uuid.UUID, principals: list[str]):
        """Owned, shared directly, or attached to an equipment the user may view."""
        return (
            (FlowRecipe.owner_id == user_id)
            | shared_with(FlowRecipe.flow_recipe_id, "flow_recipe", principals)
            | FlowRecipe.equipment_id.in_(accessible_equipment_ids(user_id, principals))
        )

    async def find_accessible(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        principals: list[str],
        skip: int = 0,
        limit: int = 100,
    ) -> list[FlowRecipe]:
        result = await session.execute(
            select(FlowRecipe)
            .where(self._accessible_filter(user_id, principals))
            .order_by(FlowRecipe.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_accessible(
        self, session: AsyncSession, user_id: uuid.UUID, principals: list[str]
    ) -> int:
        result = await session.execute(
            select(func.count()).select_from(FlowRecipe).where(self._accessible_filter(user_id, principals))
        )
        return result.scalar_one()

    async def find_all(self, session: AsyncSession, skip: int = 0, limit: int = 100) -> list[FlowRecipe]:
        result = await session.execute(
            select(FlowRecipe).order_by(FlowRecipe.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_ids(self, session: AsyncSession, ids: list[uuid.UUID]) -> list[FlowRecipe]:
        if not ids:
            return []
        result = await session.execute(select(FlowRecipe).where(FlowRecipe.flow_recipe_id.in_(ids)))
        return list(result.scalars().all())

    async def find_unowned(self, session: AsyncSession) -> list[FlowRecipe]:
        result = await session.execute(select(FlowRecipe).where(FlowRecipe.owner_id.is_(None)))
        return list(result.scalars().all())

    async def sync_equipment_link(
        self,
        session: AsyncSession,
        equipment_id: uuid.UUID,
        recipe_ids: list[uuid.UUID],
        owner_id: uuid.UUID | None = None,
    ) -> None:
        """Attach the recipes referenced by an equipment config and detach the rest.

        Recipes without an owner inherit the equipment owner. Caller commits.
        """
        if recipe_ids:
            await session.execute(
                update(FlowRecipe)
                .where(FlowRecipe.flow_recipe_id.in_(recipe_ids))
                .values(equipment_id=equipment_id)
            )
            if owner_id is not None:
                await session.execute(
                    update(FlowRecipe)
                    .where(FlowRecipe.flow_recipe_id.in_(recipe_ids), FlowRecipe.owner_id.is_(None))
                    .values(owner_id=owner_id)
                )
        detach = [FlowRecipe.equipment_id == equipment_id]
        if recipe_ids:
            detach.append(FlowRecipe.flow_recipe_id.not_in(recipe_ids))
        await session.execute(update(FlowRecipe).where(*detach).values(equipment_id=None))
