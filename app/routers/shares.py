"""Uniform sharing API for every resource type.

    GET    /shares/{resource_type}/{resource_id}
    POST   /shares/{resource_type}/{resource_id}
    DELETE /shares/{resource_type}/{resource_id}/{share_id}

resource_type: equipment | simulator | job | flow_recipe | process_recipe | module
"""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.enums import ResourceType
from app.middleware import limiter
from app.schemas.common import APIResponse
from app.schemas.share import ShareCreate, ShareRead
from app.schemas.user import UserRead
from app.services.sharing_service import SharingService

router = APIRouter(prefix="/shares", tags=["sharing"])


def _get_service() -> SharingService:
    return SharingService()


@router.get("/{resource_type}/{resource_id}", response_model=APIResponse[list[ShareRead]])
@limiter.limit("60/minute")
async def list_shares(
    request: Request,
    resource_type: ResourceType,
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Who has access to a resource (owner or admin only)."""
    return APIResponse.ok(
        await _get_service().list_shares(db, resource_type.value, resource_id, current_user.user_id)
    )


@router.post("/{resource_type}/{resource_id}", response_model=APIResponse[ShareRead])
@limiter.limit("30/minute")
async def grant_share(
    request: Request,
    resource_type: ResourceType,
    resource_id: str,
    body: ShareCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """Grant view/edit access to a user (by email), a group, or the public (admins)."""
    return APIResponse.ok(
        await _get_service().grant(db, resource_type.value, resource_id, current_user.user_id, body)
    )


@router.delete("/{resource_type}/{resource_id}/{share_id}", response_model=APIResponse[None])
@limiter.limit("30/minute")
async def revoke_share(
    request: Request,
    resource_type: ResourceType,
    resource_id: str,
    share_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    await _get_service().revoke(db, resource_type.value, resource_id, current_user.user_id, share_id)
    return APIResponse.ok(None)
