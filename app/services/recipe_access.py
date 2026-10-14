"""Shared access checks for equipment-linked resources (recipes, modules).

A recipe/module is readable by its owner, by anyone it was shared with, and by
anyone who may view the equipment it is attached to; editing follows the same
chain with edit permission. Platform admins may list metadata only.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AuthorizationError
from app.services.access import AccessPolicy


class LinkedResourceGuard:
    def __init__(self, resource_type: str, id_attr: str, access: AccessPolicy):
        self._rtype = resource_type
        self._id_attr = id_attr
        self._access = access

    @property
    def resource_type(self) -> str:
        return self._rtype

    def _args(self, row):
        return self._rtype, getattr(row, self._id_attr), row.owner_id, row.equipment_id

    async def require_view(self, session: AsyncSession, row, user_id: uuid.UUID) -> None:
        if not await self._access.can_view_linked(session, *self._args(row), user_id):
            raise AuthorizationError()

    async def require_edit(self, session: AsyncSession, row, user_id: uuid.UUID) -> None:
        if not await self._access.can_edit_linked(session, *self._args(row), user_id):
            raise AuthorizationError()

    def require_owner(self, row, user_id: uuid.UUID) -> None:
        if not self._access.is_owner(row.owner_id, user_id):
            raise AuthorizationError("Only the owner can delete this resource")
