import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ResourceType
from app.enums import audit_action as act
from app.exceptions import NotFoundError
from app.models.process_recipe import ProcessRecipe
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.common import PaginationMeta
from app.schemas.process_recipe import ProcessRecipeCreate, ProcessRecipeRead, ProcessRecipeUpdate
from app.schemas.process_recipe_config import ProcessRecipeConfig
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit
from app.services.file_storage_service import FileStorageService, file_storage
from app.services.recipe_access import LinkedResourceGuard
from app.services.sharing_service import SharingService

RTYPE = ResourceType.PROCESS_RECIPE.value


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


class ProcessRecipeService:
    def __init__(
        self,
        repo: ProcessRecipeRepository,
        storage: FileStorageService = file_storage,
        access: AccessPolicy = access_policy,
        audit_svc: AuditService = audit,
        sharing: SharingService | None = None,
    ):
        self._repo = repo
        self._storage = storage
        self._access = access
        self._guard = LinkedResourceGuard(RTYPE, "process_recipe_id", access)
        self._audit = audit_svc
        self._sharing = sharing or SharingService(access=access, audit_svc=audit_svc)

    async def _load(self, session: AsyncSession, recipe_id: uuid.UUID) -> ProcessRecipe:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("ProcessRecipe", str(recipe_id))
        return recipe

    async def create(self, session: AsyncSession, user_id: uuid.UUID, data: ProcessRecipeCreate) -> ProcessRecipeRead:
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
            "owner_id": user_id,
        })
        await self._audit.record(session, act.RESOURCE_CREATED, resource_type=RTYPE, resource_id=recipe_id,
                                 details={"name": data.process_recipe_name})
        return ProcessRecipeRead.model_validate(recipe)

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> tuple[list[ProcessRecipeRead], PaginationMeta]:
        if await self._access.is_admin(session, user_id):
            recipes = await self._repo.find_all(session, skip, limit)
            total = await self._repo.count(session)
        else:
            principals = await self._access.principals(session, user_id)
            recipes = await self._repo.find_accessible(session, user_id, principals, skip, limit)
            total = await self._repo.count_accessible(session, user_id, principals)
        return [ProcessRecipeRead.model_validate(r) for r in recipes], _meta(total, skip, limit)

    async def get(self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID) -> ProcessRecipeRead:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_view(session, recipe, user_id)
        return ProcessRecipeRead.model_validate(recipe)

    async def get_config(self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID) -> ProcessRecipeConfig:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_view(session, recipe, user_id)
        config = ProcessRecipeConfig.model_validate(self._storage.read_json(recipe.process_recipe_path))
        await self._audit.record(session, act.RESOURCE_READ, resource_type=RTYPE, resource_id=recipe_id,
                                 details={"part": "config"})
        return config

    async def update_config(
        self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID, config: ProcessRecipeConfig
    ) -> ProcessRecipeConfig:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_edit(session, recipe, user_id)
        self._storage.write_json(recipe.process_recipe_path, config.model_dump())
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=recipe_id,
                                 details={"part": "config"})
        return config

    async def update(
        self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID, data: ProcessRecipeUpdate
    ) -> ProcessRecipeRead:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_edit(session, recipe, user_id)
        changes = data.model_dump(exclude_none=True)
        updated = await self._repo.update(session, recipe_id, changes)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=recipe_id,
                                 details=changes)
        return ProcessRecipeRead.model_validate(updated)

    async def delete(self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID) -> None:
        recipe = await self._load(session, recipe_id)
        if not self._access.is_owner(recipe.owner_id, user_id):
            await self._guard.require_edit(session, recipe, user_id)
        self._storage.delete(recipe.process_recipe_path)
        await self._sharing.delete_for_resource(session, RTYPE, recipe_id)
        await self._repo.delete(session, recipe_id)
        await self._audit.record(session, act.RESOURCE_DELETED, resource_type=RTYPE, resource_id=recipe_id)
