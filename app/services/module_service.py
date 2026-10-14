import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ModuleType, ResourceType
from app.enums import audit_action as act
from app.exceptions import NotFoundError
from app.models.module import Module
from app.repositories.module_repository import ModuleRepository
from app.schemas.common import PaginationMeta
from app.schemas.module import ModuleCreate, ModuleRead, ModuleUpdate
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit
from app.services.recipe_access import LinkedResourceGuard
from app.services.sharing_service import SharingService

RTYPE = ResourceType.MODULE.value


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


class ModuleService:
    def __init__(
        self,
        repo: ModuleRepository,
        access: AccessPolicy = access_policy,
        audit_svc: AuditService = audit,
        sharing: SharingService | None = None,
    ):
        self._repo = repo
        self._access = access
        self._guard = LinkedResourceGuard(RTYPE, "module_id", access)
        self._audit = audit_svc
        self._sharing = sharing or SharingService(access=access, audit_svc=audit_svc)

    async def _load(self, session: AsyncSession, module_id: int) -> Module:
        module = await self._repo.find_by_id(session, module_id)
        if module is None:
            raise NotFoundError("Module", module_id)
        return module

    async def create(self, session: AsyncSession, user_id: uuid.UUID, data: ModuleCreate) -> ModuleRead:
        module = await self._repo.create(session, {**data.model_dump(), "owner_id": user_id})
        await self._audit.record(session, act.RESOURCE_CREATED, resource_type=RTYPE, resource_id=module.module_id,
                                 details={"name": data.module_name, "type": data.module_type})
        return ModuleRead.model_validate(module)

    async def list_for_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        module_type: ModuleType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ModuleRead], PaginationMeta]:
        if await self._access.is_admin(session, user_id):
            modules = (
                await self._repo.find_by_type(session, module_type, skip, limit)
                if module_type else await self._repo.find_all(session, skip, limit)
            )
            total = await self._repo.count_by_type(session, module_type)
        else:
            principals = await self._access.principals(session, user_id)
            modules = await self._repo.find_accessible(session, user_id, principals, module_type, skip, limit)
            total = await self._repo.count_accessible(session, user_id, principals, module_type)
        return [ModuleRead.model_validate(m) for m in modules], _meta(total, skip, limit)

    async def get(self, session: AsyncSession, module_id: int, user_id: uuid.UUID) -> ModuleRead:
        module = await self._load(session, module_id)
        await self._guard.require_view(session, module, user_id)
        return ModuleRead.model_validate(module)

    async def update(
        self, session: AsyncSession, module_id: int, user_id: uuid.UUID, data: ModuleUpdate
    ) -> ModuleRead:
        module = await self._load(session, module_id)
        await self._guard.require_edit(session, module, user_id)
        changes = data.model_dump(exclude_none=True)
        updated = await self._repo.update(session, module_id, changes)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=module_id,
                                 details=changes)
        return ModuleRead.model_validate(updated)

    async def delete(self, session: AsyncSession, module_id: int, user_id: uuid.UUID) -> None:
        module = await self._load(session, module_id)
        if not self._access.is_owner(module.owner_id, user_id):
            await self._guard.require_edit(session, module, user_id)
        await self._sharing.delete_for_resource(session, RTYPE, module_id)
        await self._repo.delete(session, module_id)
        await self._audit.record(session, act.RESOURCE_DELETED, resource_type=RTYPE, resource_id=module_id)
