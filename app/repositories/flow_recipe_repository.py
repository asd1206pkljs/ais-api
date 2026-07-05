from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow_recipe import FlowRecipe
from app.repositories.base import BaseRepository


class FlowRecipeRepository(BaseRepository[FlowRecipe]):
    def __init__(self):
        super().__init__(FlowRecipe)

    async def find_by_id(self, session: AsyncSession, entity_id) -> FlowRecipe | None:
        result = await session.execute(
            select(FlowRecipe).where(FlowRecipe.flow_recipe_id == entity_id)
        )
        return result.scalar_one_or_none()
