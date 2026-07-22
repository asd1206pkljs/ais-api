import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_internal_or_user
from app.middleware import limiter
from app.repositories.simulator_repository import SimulatorRepository
from app.schemas.common import APIResponse
from app.schemas.simulator import (
    SimulatorAccessUserRequest,
    SimulatorCreate,
    SimulatorRead,
    SimulatorUpdate,
)
from app.schemas.simulator_config import SimulatorConfig
from app.schemas.user import UserRead
from app.services.simulator_service import SimulatorService

router = APIRouter(prefix="/simulators", tags=["simulators"])
_repo = SimulatorRepository()


def _get_service() -> SimulatorService:
    return SimulatorService(_repo)


@router.get("", response_model=APIResponse[list[SimulatorRead]])
@limiter.limit("60/minute")
async def list_simulators(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_internal_or_user),
):
    svc = _get_service()
    simulators = await svc.list_by_owner(db, user_id, skip, limit)
    return APIResponse.ok(simulators)


@router.post("", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def create_simulator(
    request: Request,
    body: SimulatorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.create(db, current_user.user_id, body)
    return APIResponse.ok(sim)


@router.post("/{simulator_id}/copy", response_model=APIResponse[SimulatorRead])
@limiter.limit("30/minute")
async def copy_simulator(
    request: Request,
    simulator_id: uuid.UUID,
    body: SimulatorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.copy(db, simulator_id, current_user.user_id, body.simulator_name)
    return APIResponse.ok(sim)


@router.get("/{simulator_id}", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def get_simulator(
    request: Request,
    simulator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.get(db, simulator_id, current_user.user_id)
    return APIResponse.ok(sim)


@router.put("/{simulator_id}", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def update_simulator(
    request: Request,
    simulator_id: uuid.UUID,
    body: SimulatorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.update(db, simulator_id, current_user.user_id, body)
    return APIResponse.ok(sim)


@router.delete("/{simulator_id}", response_model=APIResponse[None])
@limiter.limit("60/minute")
async def delete_simulator(
    request: Request,
    simulator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    await svc.delete(db, simulator_id, current_user.user_id)
    return APIResponse.ok(None)


@router.post("/{simulator_id}/generate", response_model=APIResponse[dict])
@limiter.limit("10/minute")
async def generate_simulator(
    request: Request,
    simulator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_internal_or_user),
):
    svc = _get_service()
    output_dir = await svc.generate(db, simulator_id, user_id)
    return APIResponse.ok({"output_dir": output_dir})


@router.get("/{simulator_id}/config", response_model=APIResponse[SimulatorConfig])
@limiter.limit("60/minute")
async def get_simulator_config(
    request: Request,
    simulator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.get_config(db, simulator_id, current_user.user_id)
    return APIResponse.ok(config)


@router.put("/{simulator_id}/config", response_model=APIResponse[SimulatorConfig])
@limiter.limit("60/minute")
async def update_simulator_config(
    request: Request,
    simulator_id: uuid.UUID,
    body: SimulatorConfig,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    config = await svc.update_config(db, simulator_id, current_user.user_id, body)
    return APIResponse.ok(config)


@router.post("/{simulator_id}/viewers", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def add_viewer(
    request: Request,
    simulator_id: uuid.UUID,
    body: SimulatorAccessUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.add_viewer(db, simulator_id, current_user.user_id, body.user_id)
    return APIResponse.ok(sim)


@router.delete("/{simulator_id}/viewers/{viewer_id}", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def remove_viewer(
    request: Request,
    simulator_id: uuid.UUID,
    viewer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.remove_viewer(db, simulator_id, current_user.user_id, viewer_id)
    return APIResponse.ok(sim)


@router.post("/{simulator_id}/editors", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def add_editor(
    request: Request,
    simulator_id: uuid.UUID,
    body: SimulatorAccessUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.add_editor(db, simulator_id, current_user.user_id, body.user_id)
    return APIResponse.ok(sim)


@router.delete("/{simulator_id}/editors/{editor_id}", response_model=APIResponse[SimulatorRead])
@limiter.limit("60/minute")
async def remove_editor(
    request: Request,
    simulator_id: uuid.UUID,
    editor_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    svc = _get_service()
    sim = await svc.remove_editor(db, simulator_id, current_user.user_id, editor_id)
    return APIResponse.ok(sim)
