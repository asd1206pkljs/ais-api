from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ModuleType
from app.exceptions import NotFoundError
from app.repositories.module_repository import ModuleRepository
from app.schemas.common import PaginationMeta
from app.schemas.module import ModuleCreate, ModuleRead, ModuleUpdate


class ModuleService:
    def __init__(self, repo: ModuleRepository):
        self._repo = repo

    async def create(self, session: AsyncSession, data: ModuleCreate) -> ModuleRead:
        module = await self._repo.create(session, data.model_dump())
        return ModuleRead.model_validate(module)

    async def list_all(
        self,
        session: AsyncSession,
        module_type: ModuleType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ModuleRead], PaginationMeta]:
        if module_type:
            modules = await self._repo.find_by_type(session, module_type, skip, limit)
            total = len(modules)
        else:
            modules = await self._repo.find_all(session, skip, limit)
            total = await self._repo.count(session)
        pages = (total + limit - 1) // limit if limit > 0 else 0
        meta = PaginationMeta(total=total, page=(skip // limit) + 1, limit=limit, pages=pages)
        return [ModuleRead.model_validate(m) for m in modules], meta

    async def get(self, session: AsyncSession, module_id: int) -> ModuleRead:
        module = await self._repo.find_by_id(session, module_id)
        if module is None:
            raise NotFoundError("Module", module_id)
        return ModuleRead.model_validate(module)

    async def update(
        self, session: AsyncSession, module_id: int, data: ModuleUpdate
    ) -> ModuleRead:
        updated = await self._repo.update(session, module_id, data.model_dump(exclude_none=True))
        if updated is None:
            raise NotFoundError("Module", module_id)
        return ModuleRead.model_validate(updated)

    async def delete(self, session: AsyncSession, module_id: int) -> None:
        deleted = await self._repo.delete(session, module_id)
        if not deleted:
            raise NotFoundError("Module", module_id)
