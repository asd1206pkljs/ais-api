from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.enums import ModuleType
from app.middleware import limiter
from app.repositories.module_repository import ModuleRepository
from app.schemas.common import APIResponse
from app.schemas.module import ModuleCreate, ModuleRead, ModuleUpdate
from app.schemas.user import UserRead
from app.services.module_service import ModuleService

router = APIRouter(prefix="/modules", tags=["modules"])
_repo = ModuleRepository()


def _get_service() -> ModuleService:
    return ModuleService(_repo)


@router.post("", response_model=APIResponse[ModuleRead])
@limiter.limit("60/minute")
async def create_module(
    request: Request,
    body: ModuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    module = await svc.create(db, body)
    return APIResponse.ok(module)


@router.get("", response_model=APIResponse[list[ModuleRead]])
@limiter.limit("60/minute")
async def list_modules(
    request: Request,
    module_type: ModuleType | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    modules, meta = await svc.list_all(db, module_type, skip, limit)
    return APIResponse.ok(modules, meta)


@router.get("/{module_id}", response_model=APIResponse[ModuleRead])
@limiter.limit("60/minute")
async def get_module(
    request: Request,
    module_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    module = await svc.get(db, module_id)
    return APIResponse.ok(module)


@router.put("/{module_id}", response_model=APIResponse[ModuleRead])
@limiter.limit("60/minute")
async def update_module(
    request: Request,
    module_id: int,
    body: ModuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    module = await svc.update(db, module_id, body)
    return APIResponse.ok(module)


@router.delete("/{module_id}", response_model=APIResponse[None])
@limiter.limit("60/minute")
async def delete_module(
    request: Request,
    module_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    await svc.delete(db, module_id)
    return APIResponse.ok(None)
