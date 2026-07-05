import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.common import PaginationMeta
from app.schemas.process_recipe import ProcessRecipeCreate, ProcessRecipeRead, ProcessRecipeUpdate
from app.schemas.process_recipe_config import ProcessRecipeConfig
from app.services.file_storage_service import FileStorageService, file_storage


class ProcessRecipeService:
    def __init__(self, repo: ProcessRecipeRepository, storage: FileStorageService = file_storage):
        self._repo = repo
        self._storage = storage

    async def create(self, session: AsyncSession, data: ProcessRecipeCreate) -> ProcessRecipeRead:
        recipe_id = uuid.uuid4()
        rel_path = self._storage.process_recipe_path(recipe_id)
        abs_path = self._storage.write_json(rel_path, {
            "process_recipe_name": data.process_recipe_name,
            "user_added_process_modules": [],
            "process_time": {},
        })
        recipe = await self._repo.create(session, {
            "process_recipe_id": recipe_id,
            "process_recipe_name": data.process_recipe_name,
            "process_recipe_path": abs_path,
            "save_status": data.save_status,
        })
        return ProcessRecipeRead.model_validate(recipe)

    async def list_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> tuple[list[ProcessRecipeRead], PaginationMeta]:
        recipes = await self._repo.find_all(session, skip, limit)
        total = await self._repo.count(session)
        pages = (total + limit - 1) // limit if limit > 0 else 0
        meta = PaginationMeta(total=total, page=(skip // limit) + 1, limit=limit, pages=pages)
        return [ProcessRecipeRead.model_validate(r) for r in recipes], meta

    async def get(self, session: AsyncSession, recipe_id: uuid.UUID) -> ProcessRecipeRead:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("ProcessRecipe", str(recipe_id))
        return ProcessRecipeRead.model_validate(recipe)

    async def get_config(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> ProcessRecipeConfig:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("ProcessRecipe", str(recipe_id))
        data = self._storage.read_json(recipe.process_recipe_path)
        return ProcessRecipeConfig.model_validate(data)

    async def update_config(
        self, session: AsyncSession, recipe_id: uuid.UUID, config: ProcessRecipeConfig
    ) -> ProcessRecipeConfig:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("ProcessRecipe", str(recipe_id))
        self._storage.write_json(recipe.process_recipe_path, config.model_dump())
        return config

    async def update(
        self, session: AsyncSession, recipe_id: uuid.UUID, data: ProcessRecipeUpdate
    ) -> ProcessRecipeRead:
        updated = await self._repo.update(
            session, recipe_id, data.model_dump(exclude_none=True)
        )
        if updated is None:
            raise NotFoundError("ProcessRecipe", str(recipe_id))
        return ProcessRecipeRead.model_validate(updated)

    async def delete(self, session: AsyncSession, recipe_id: uuid.UUID) -> None:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("ProcessRecipe", str(recipe_id))
        self._storage.delete(recipe.process_recipe_path)
        await self._repo.delete(session, recipe_id)
