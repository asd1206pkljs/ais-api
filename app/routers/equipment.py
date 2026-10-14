import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.middleware import limiter
from app.repositories.equipment_repository import EquipmentRepository
from app.schemas.common import APIResponse
from app.schemas.equipment import AccessUserRequest, EquipmentCreate, EquipmentRead, EquipmentUpdate
from app.schemas.equipment_config import EquipmentConfig
from app.schemas.user import UserRead
from app.services.equipment_service import EquipmentService
from app.services.eqp_model_service import generate_eqp_model

router = APIRouter(prefix="/equipment", tags=["equipment"])
_repo = EquipmentRepository()


def _get_service() -> EquipmentService:
    return EquipmentService(_repo)


@router.get("", response_model=APIResponse[list[EquipmentRead]])
@limiter.limit("60/minute")
async def list_equipment(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    equipments = await svc.list_by_owner(db, current_user.user_id, skip, limit)
    return APIResponse.ok(equipments)


@router.post("", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def create_equipment(
    request: Request,
    body: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.create(db, current_user.user_id, body)
    return APIResponse.ok(eq)


@router.post("/{equipment_id}/copy", response_model=APIResponse[EquipmentRead])
@limiter.limit("30/minute")
async def copy_equipment(
    request: Request,
    equipment_id: uuid.UUID,
    body: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.copy(db, equipment_id, current_user.user_id, body.equipment_name)
    return APIResponse.ok(eq)


@router.get("/{equipment_id}", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def get_equipment(
    request: Request,
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.get(db, equipment_id, current_user.user_id)
    return APIResponse.ok(eq)


@router.put("/{equipment_id}", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def update_equipment(
    request: Request,
    equipment_id: uuid.UUID,
    body: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.update(db, equipment_id, current_user.user_id, body)
    return APIResponse.ok(eq)


@router.delete("/{equipment_id}", response_model=APIResponse[None])
@limiter.limit("60/minute")
async def delete_equipment(
    request: Request,
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    await svc.delete(db, equipment_id, current_user.user_id)
    return APIResponse.ok(None)


@router.get("/{equipment_id}/config", response_model=APIResponse[EquipmentConfig])
@limiter.limit("60/minute")
async def get_equipment_config(
    request: Request,
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.get_config(db, equipment_id, current_user.user_id)
    return APIResponse.ok(config)


@router.put("/{equipment_id}/config", response_model=APIResponse[EquipmentConfig])
@limiter.limit("60/minute")
async def update_equipment_config(
    request: Request,
    equipment_id: uuid.UUID,
    body: EquipmentConfig,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.update_config(db, equipment_id, current_user.user_id, body)
    return APIResponse.ok(config)


@router.post("/{equipment_id}/generate", response_model=APIResponse[dict])
@limiter.limit("10/minute")
async def generate_equipment_model(
    request: Request,
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    output_dir = await generate_eqp_model(db, equipment_id, current_user.user_id)
    # Only the model name leaves the server; absolute paths are internal.
    return APIResponse.ok({"eqp_model": Path(output_dir).name})


@router.post("/{equipment_id}/viewers", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def add_viewer(
    request: Request,
    equipment_id: uuid.UUID,
    body: AccessUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.add_viewer(db, equipment_id, current_user.user_id, body.user_id)
    return APIResponse.ok(eq)


@router.delete("/{equipment_id}/viewers/{viewer_id}", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def remove_viewer(
    request: Request,
    equipment_id: uuid.UUID,
    viewer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.remove_viewer(db, equipment_id, current_user.user_id, viewer_id)
    return APIResponse.ok(eq)


@router.post("/{equipment_id}/editors", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def add_editor(
    request: Request,
    equipment_id: uuid.UUID,
    body: AccessUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.add_editor(db, equipment_id, current_user.user_id, body.user_id)
    return APIResponse.ok(eq)


@router.delete("/{equipment_id}/editors/{editor_id}", response_model=APIResponse[EquipmentRead])
@limiter.limit("60/minute")
async def remove_editor(
    request: Request,
    equipment_id: uuid.UUID,
    editor_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    eq = await svc.remove_editor(db, equipment_id, current_user.user_id, editor_id)
    return APIResponse.ok(eq)
