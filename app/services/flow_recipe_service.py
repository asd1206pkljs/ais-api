import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ResourceType
from app.enums import audit_action as act
from app.exceptions import NotFoundError, ValidationError
from app.models.flow_recipe import FlowRecipe
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.common import PaginationMeta
from app.schemas.flow_recipe import FlowRecipeCreate, FlowRecipeRead, FlowRecipeUpdate
from app.schemas.flow_recipe_config import FlowRecipeConfig
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit
from app.services.file_storage_service import FileStorageService, file_storage
from app.services.recipe_access import LinkedResourceGuard
from app.services.sharing_service import SharingService

RTYPE = ResourceType.FLOW_RECIPE.value


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


class FlowRecipeService:
    def __init__(
        self,
        repo: FlowRecipeRepository,
        process_recipe_repo: ProcessRecipeRepository,
        storage: FileStorageService = file_storage,
        access: AccessPolicy = access_policy,
        audit_svc: AuditService = audit,
        sharing: SharingService | None = None,
    ):
        self._repo = repo
        self._process_repo = process_recipe_repo
        self._storage = storage
        self._access = access
        self._guard = LinkedResourceGuard(RTYPE, "flow_recipe_id", access)
        self._audit = audit_svc
        self._sharing = sharing or SharingService(access=access, audit_svc=audit_svc)

    async def _load(self, session: AsyncSession, recipe_id: uuid.UUID) -> FlowRecipe:
        recipe = await self._repo.find_by_id(session, recipe_id)
        if recipe is None:
            raise NotFoundError("FlowRecipe", str(recipe_id))
        return recipe

    async def _validate_process_recipe_ids(
        self, session: AsyncSession, config: FlowRecipeConfig, user_id: uuid.UUID
    ) -> None:
        for step in config.process_recipe_steps:
            try:
                rid = uuid.UUID(step.process_recipe_id)
            except ValueError as e:
                raise ValidationError(f"Invalid process_recipe_id: {step.process_recipe_id}") from e
            recipe = await self._process_repo.find_by_id(session, rid)
            if recipe is None:
                raise ValidationError(f"ProcessRecipe '{step.process_recipe_id}' not found")
            # Referencing someone else's recipe would leak it through the flow.
            if not await self._access.can_view_linked(
                session, ResourceType.PROCESS_RECIPE.value, recipe.process_recipe_id,
                recipe.owner_id, recipe.equipment_id, user_id,
            ):
                raise ValidationError(f"ProcessRecipe '{step.process_recipe_id}' not found")

    async def create(self, session: AsyncSession, user_id: uuid.UUID, data: FlowRecipeCreate) -> FlowRecipeRead:
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
            "owner_id": user_id,
        })
        await self._audit.record(session, act.RESOURCE_CREATED, resource_type=RTYPE, resource_id=recipe_id,
                                 details={"name": data.flow_recipe_name})
        return FlowRecipeRead.model_validate(recipe)

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> tuple[list[FlowRecipeRead], PaginationMeta]:
        if await self._access.is_admin(session, user_id):
            recipes = await self._repo.find_all(session, skip, limit)
            total = await self._repo.count(session)
        else:
            principals = await self._access.principals(session, user_id)
            recipes = await self._repo.find_accessible(session, user_id, principals, skip, limit)
            total = await self._repo.count_accessible(session, user_id, principals)
        return [FlowRecipeRead.model_validate(r) for r in recipes], _meta(total, skip, limit)

    async def get(self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID) -> FlowRecipeRead:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_view(session, recipe, user_id)
        return FlowRecipeRead.model_validate(recipe)

    async def get_config(self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID) -> FlowRecipeConfig:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_view(session, recipe, user_id)
        config = FlowRecipeConfig.model_validate(self._storage.read_json(recipe.flow_recipe_path))
        await self._audit.record(session, act.RESOURCE_READ, resource_type=RTYPE, resource_id=recipe_id,
                                 details={"part": "config"})
        return config

    async def update_config(
        self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID, config: FlowRecipeConfig
    ) -> FlowRecipeConfig:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_edit(session, recipe, user_id)
        await self._validate_process_recipe_ids(session, config, user_id)
        self._storage.write_json(recipe.flow_recipe_path, config.model_dump())
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=recipe_id,
                                 details={"part": "config"})
        return config

    async def update(
        self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID, data: FlowRecipeUpdate
    ) -> FlowRecipeRead:
        recipe = await self._load(session, recipe_id)
        await self._guard.require_edit(session, recipe, user_id)
        changes = data.model_dump(exclude_none=True)
        updated = await self._repo.update(session, recipe_id, changes)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=recipe_id,
                                 details=changes)
        return FlowRecipeRead.model_validate(updated)

    async def delete(self, session: AsyncSession, recipe_id: uuid.UUID, user_id: uuid.UUID) -> None:
        recipe = await self._load(session, recipe_id)
        # Owner, or an editor of the equipment it belongs to (recipes are part of its config).
        if not self._access.is_owner(recipe.owner_id, user_id):
            await self._guard.require_edit(session, recipe, user_id)
        self._storage.delete(recipe.flow_recipe_path)
        await self._sharing.delete_for_resource(session, RTYPE, recipe_id)
        await self._repo.delete(session, recipe_id)
        await self._audit.record(session, act.RESOURCE_DELETED, resource_type=RTYPE, resource_id=recipe_id)
