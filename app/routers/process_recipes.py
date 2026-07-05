import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.middleware import limiter
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.common import APIResponse
from app.schemas.process_recipe import ProcessRecipeCreate, ProcessRecipeRead, ProcessRecipeUpdate
from app.schemas.process_recipe_config import ProcessRecipeConfig
from app.schemas.user import UserRead
from app.services.process_recipe_service import ProcessRecipeService

router = APIRouter(prefix="/process-recipes", tags=["process-recipes"])
_repo = ProcessRecipeRepository()


def _get_service() -> ProcessRecipeService:
    return ProcessRecipeService(_repo)


@router.post("", response_model=APIResponse[ProcessRecipeRead])
@limiter.limit("60/minute")
async def create_process_recipe(
    request: Request,
    body: ProcessRecipeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipe = await svc.create(db, body)
    return APIResponse.ok(recipe)


@router.get("", response_model=APIResponse[list[ProcessRecipeRead]])
@limiter.limit("60/minute")
async def list_process_recipes(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipes, meta = await svc.list_all(db, skip, limit)
    return APIResponse.ok(recipes, meta)


@router.get("/{recipe_id}", response_model=APIResponse[ProcessRecipeRead])
@limiter.limit("60/minute")
async def get_process_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipe = await svc.get(db, recipe_id)
    return APIResponse.ok(recipe)


@router.get("/{recipe_id}/config", response_model=APIResponse[ProcessRecipeConfig])
@limiter.limit("60/minute")
async def get_process_recipe_config(
    request: Request,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.get_config(db, recipe_id)
    return APIResponse.ok(config)


@router.put("/{recipe_id}/config", response_model=APIResponse[ProcessRecipeConfig])
@limiter.limit("60/minute")
async def update_process_recipe_config(
    request: Request,
    recipe_id: uuid.UUID,
    body: ProcessRecipeConfig,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.update_config(db, recipe_id, body)
    return APIResponse.ok(config)


@router.put("/{recipe_id}", response_model=APIResponse[ProcessRecipeRead])
@limiter.limit("60/minute")
async def update_process_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    body: ProcessRecipeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipe = await svc.update(db, recipe_id, body)
    return APIResponse.ok(recipe)


@router.delete("/{recipe_id}", response_model=APIResponse[None])
@limiter.limit("60/minute")
async def delete_process_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    await svc.delete(db, recipe_id)
    return APIResponse.ok(None)
