from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.process_recipe import ProcessRecipe
from app.repositories.base import BaseRepository


class ProcessRecipeRepository(BaseRepository[ProcessRecipe]):
    def __init__(self):
        super().__init__(ProcessRecipe)

    async def find_by_id(self, session: AsyncSession, entity_id) -> ProcessRecipe | None:
        result = await session.execute(
            select(ProcessRecipe).where(ProcessRecipe.process_recipe_id == entity_id)
        )
        return result.scalar_one_or_none()
