import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.middleware import limiter
from app.schemas.common import APIResponse
from app.schemas.group import (
    GroupCreate,
    GroupDetail,
    GroupMemberAdd,
    GroupMemberUpdate,
    GroupRead,
    GroupUpdate,
)
from app.schemas.user import UserRead
from app.services.group_service import GroupService

router = APIRouter(prefix="/groups", tags=["groups"])


def _get_service() -> GroupService:
    return GroupService()


@router.post("", response_model=APIResponse[GroupRead])
@limiter.limit("20/minute")
async def create_group(
    request: Request,
    body: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Create a group; the creator becomes its first group admin."""
    return APIResponse.ok(await _get_service().create(db, current_user.user_id, body))


@router.get("", response_model=APIResponse[list[GroupRead]])
@limiter.limit("60/minute")
async def list_my_groups(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    return APIResponse.ok(await _get_service().list_mine(db, current_user.user_id))


@router.get("/{group_id}", response_model=APIResponse[GroupDetail])
@limiter.limit("60/minute")
async def get_group(
    request: Request,
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Group with its members. Members only."""
    return APIResponse.ok(await _get_service().get(db, group_id, current_user.user_id))


@router.patch("/{group_id}", response_model=APIResponse[GroupRead])
@limiter.limit("30/minute")
async def update_group(
    request: Request,
    group_id: uuid.UUID,
    body: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    return APIResponse.ok(await _get_service().update(db, group_id, current_user.user_id, body))


@router.delete("/{group_id}", response_model=APIResponse[None])
@limiter.limit("10/minute")
async def delete_group(
    request: Request,
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    await _get_service().delete(db, group_id, current_user.user_id)
    return APIResponse.ok(None)


@router.post("/{group_id}/members", response_model=APIResponse[GroupDetail])
@limiter.limit("30/minute")
async def add_member(
    request: Request,
    group_id: uuid.UUID,
    body: GroupMemberAdd,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Add an existing, active account to the group by email (group admins)."""
    return APIResponse.ok(await _get_service().add_member(db, group_id, current_user.user_id, body))


@router.patch("/{group_id}/members/{member_id}", response_model=APIResponse[GroupDetail])
@limiter.limit("30/minute")
async def update_member(
    request: Request,
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    body: GroupMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    return APIResponse.ok(
        await _get_service().update_member(db, group_id, current_user.user_id, member_id, body.role)
    )


@router.delete("/{group_id}/members/{member_id}", response_model=APIResponse[None])
@limiter.limit("30/minute")
async def remove_member(
    request: Request,
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Remove a member (group admins), or leave the group (member_id = yourself)."""
    await _get_service().remove_member(db, group_id, current_user.user_id, member_id)
    return APIResponse.ok(None)
