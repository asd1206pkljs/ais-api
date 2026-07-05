import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.middleware import limiter
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.common import APIResponse
from app.schemas.flow_recipe import FlowRecipeCreate, FlowRecipeRead, FlowRecipeUpdate
from app.schemas.flow_recipe_config import FlowRecipeConfig
from app.schemas.user import UserRead
from app.services.flow_recipe_service import FlowRecipeService

router = APIRouter(prefix="/flow-recipes", tags=["flow-recipes"])
_repo = FlowRecipeRepository()
_process_repo = ProcessRecipeRepository()


def _get_service() -> FlowRecipeService:
    return FlowRecipeService(_repo, _process_repo)


@router.post("", response_model=APIResponse[FlowRecipeRead])
@limiter.limit("60/minute")
async def create_flow_recipe(
    request: Request,
    body: FlowRecipeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipe = await svc.create(db, body)
    return APIResponse.ok(recipe)


@router.get("", response_model=APIResponse[list[FlowRecipeRead]])
@limiter.limit("60/minute")
async def list_flow_recipes(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipes, meta = await svc.list_all(db, skip, limit)
    return APIResponse.ok(recipes, meta)


@router.get("/{recipe_id}", response_model=APIResponse[FlowRecipeRead])
@limiter.limit("60/minute")
async def get_flow_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipe = await svc.get(db, recipe_id)
    return APIResponse.ok(recipe)


@router.get("/{recipe_id}/config", response_model=APIResponse[FlowRecipeConfig])
@limiter.limit("60/minute")
async def get_flow_recipe_config(
    request: Request,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.get_config(db, recipe_id)
    return APIResponse.ok(config)


@router.put("/{recipe_id}/config", response_model=APIResponse[FlowRecipeConfig])
@limiter.limit("60/minute")
async def update_flow_recipe_config(
    request: Request,
    recipe_id: uuid.UUID,
    body: FlowRecipeConfig,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.update_config(db, recipe_id, body)
    return APIResponse.ok(config)


@router.put("/{recipe_id}", response_model=APIResponse[FlowRecipeRead])
@limiter.limit("60/minute")
async def update_flow_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    body: FlowRecipeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    recipe = await svc.update(db, recipe_id, body)
    return APIResponse.ok(recipe)


@router.delete("/{recipe_id}", response_model=APIResponse[None])
@limiter.limit("60/minute")
async def delete_flow_recipe(
    request: Request,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    await svc.delete(db, recipe_id)
    return APIResponse.ok(None)
