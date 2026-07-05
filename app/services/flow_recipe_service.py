import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError, ValidationError
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.common import PaginationMeta
from app.schemas.flow_recipe import FlowRecipeCreate, FlowRecipeRead, FlowRecipeUpdate
from app.schemas.flow_recipe_config import FlowRecipeConfig
from app.services.file_storage_service import FileStorageService, file_storage


class FlowRecipeService:
    def __init__(
        self,
        repo: FlowRecipeRepository,
        process_recipe_repo: ProcessRecipeRepository,
        storage: FileStorageService = file_storage,
    ):
        self._repo = repo
        self._process_repo = process_recipe_repo
        self._storage = storage

    async def _validate_process_recipe_ids(
        self, session: AsyncSession, config: FlowRecipeConfig
    ) -> None:
        for step in config.process_recipe_steps:
            try:
                rid = uuid.UUID(step.process_recipe_id)
            except ValueError as e:
                raise ValidationError(
                    f"Invalid process_recipe_id: {step.process_recipe_id}"
                ) from e
            recipe = await self._process_repo.find_by_id(session, rid)
            if recipe is None:
                raise ValidationError(
                    f"ProcessRecipe '{step.process_recipe_id}' not found"
                )

    async def create(self, session: AsyncSession, data: FlowRecipeCreate) -> FlowRecipeRead:
        recipe_id = uuid.uuid4()
        rel_path = self._storage.flow_recipe_path(recipe_id)
        abs_path = self._storage.write_json(rel_path, {
            "flow_recipe_name": data.flow_recipe_name,
            "num_process_steps": 0,
            "process_recipe_steps": [],
            "module_sequence": [],
        })
        recipe = await self._repo.create(session, {
            "flow_recipe_id": recipe_id,
            "flow_recipe_name": data.flow_recipe_name,
            "flow_recipe_path": abs_path,
            "save_status": data.save_status,
        })
        return FlowRecipeRead.model_validate(recipe)

    async def list_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> tuple[list[FlowRecipeRead], PaginationMeta]:
        recipes = await self._repo.find_all(session, skip, limit)
        total = await self._repo.count(session)
        pages = (total + limit - 1) // limit if limit > 0 else 0
        meta = PaginationMeta(total=total, page=(skip // limit) + 1, limit=limit, pages=pages)
        return [FlowRecipeRead.model_validate(r) for r in recipes], meta

    async def get(self, session: AsyncSession, recipe_id: uuid.UUID) -> FlowRecipeRead:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("FlowRecipe", str(recipe_id))
        return FlowRecipeRead.model_validate(recipe)

    async def get_config(
        self, session: AsyncSession, recipe_id: uuid.UUID
    ) -> FlowRecipeConfig:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("FlowRecipe", str(recipe_id))
        data = self._storage.read_json(recipe.flow_recipe_path)
        return FlowRecipeConfig.model_validate(data)

    async def update_config(
        self, session: AsyncSession, recipe_id: uuid.UUID, config: FlowRecipeConfig
    ) -> FlowRecipeConfig:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("FlowRecipe", str(recipe_id))
        await self._validate_process_recipe_ids(session, config)
        self._storage.write_json(recipe.flow_recipe_path, config.model_dump())
        return config

    async def update(
        self, session: AsyncSession, recipe_id: uuid.UUID, data: FlowRecipeUpdate
    ) -> FlowRecipeRead:
        updated = await self._repo.update(
            session, recipe_id, data.model_dump(exclude_none=True)
        )
        if updated is None:
            raise NotFoundError("FlowRecipe", str(recipe_id))
        return FlowRecipeRead.model_validate(updated)

    async def delete(self, session: AsyncSession, recipe_id: uuid.UUID) -> None:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("FlowRecipe", str(recipe_id))
        self._storage.delete(recipe.flow_recipe_path)
        await self._repo.delete(session, recipe_id)
