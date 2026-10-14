"""Server-side access decisions. Every read/update/delete goes through here.

Principals of a user = their own id, the ids of the groups they belong to, and
"*" (public). A share for any of them grants access. Platform admins get no
implicit access to resource *content*; services expose only metadata to them.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import PUBLIC_PRINCIPAL_ID, SharePermission, UserRole
from app.repositories.group_repository import GroupRepository
from app.repositories.resource_share_repository import ResourceShareRepository
from app.repositories.user_repository import UserRepository

_user_repo = UserRepository()


def is_admin_user(user) -> bool:
    """Role check on an already-loaded user (or UserRead)."""
    if user is None:
        return False
    if getattr(user, "role", None) == UserRole.ADMIN.value:
        return True
    # Bootstrap list from .env so the first admin can exist before roles are set.
    email = getattr(user, "user_email", None) or ""
    return email.lower() in settings.admin_emails


async def is_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if the user holds the platform admin role.

    Admins may list every resource's metadata and manage users, groups and
    public sharing. They do not get access to resource content.
    """
    user = await _user_repo.find_by_id(session, user_id)
    return is_admin_user(user)


class AccessPolicy:
    def __init__(
        self,
        share_repo: ResourceShareRepository | None = None,
        group_repo: GroupRepository | None = None,
        user_repo: UserRepository | None = None,
    ):
        self._shares = share_repo or ResourceShareRepository()
        self._groups = group_repo or GroupRepository()
        self._users = user_repo or _user_repo

    async def is_admin(self, session: AsyncSession, user_id: uuid.UUID) -> bool:
        return is_admin_user(await self._users.find_by_id(session, user_id))

    async def principals(self, session: AsyncSession, user_id: uuid.UUID) -> list[str]:
        group_ids = await self._groups.member_group_ids(session, user_id)
        return [str(user_id), *(str(g) for g in group_ids), PUBLIC_PRINCIPAL_ID]

    @staticmethod
    def is_owner(owner_id: uuid.UUID | None, user_id: uuid.UUID) -> bool:
        return owner_id is not None and owner_id == user_id

    async def _has(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_id: object,
        owner_id: uuid.UUID | None,
        user_id: uuid.UUID,
        permission: str,
    ) -> bool:
        if self.is_owner(owner_id, user_id):
            return True
        principals = await self.principals(session, user_id)
        return await self._shares.has_permission(
            session, resource_type, str(resource_id), principals, permission
        )

    async def can_view(
        self, session: AsyncSession, resource_type: str, resource_id: object,
        owner_id: uuid.UUID | None, user_id: uuid.UUID,
    ) -> bool:
        return await self._has(session, resource_type, resource_id, owner_id, user_id,
                               SharePermission.VIEW.value)

    async def can_edit(
        self, session: AsyncSession, resource_type: str, resource_id: object,
        owner_id: uuid.UUID | None, user_id: uuid.UUID,
    ) -> bool:
        return await self._has(session, resource_type, resource_id, owner_id, user_id,
                               SharePermission.EDIT.value)

    async def _linked(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_id: object,
        owner_id: uuid.UUID | None,
        equipment_id: uuid.UUID | None,
        user_id: uuid.UUID,
        permission: str,
    ) -> bool:
        """Recipes/modules: own grant, or inherited from the equipment using them."""
        if await self._has(session, resource_type, resource_id, owner_id, user_id, permission):
            return True
        if equipment_id is None:
            return False
        from app.repositories.equipment_repository import EquipmentRepository  # avoid import cycle

        equipment = await EquipmentRepository().find_by_id(session, equipment_id)
        if equipment is None or equipment.save_status == "deleted":
            return False
        return await self._has(
            session, "equipment", equipment.equipment_id, equipment.owner_id, user_id, permission
        )

    async def can_view_linked(
        self, session: AsyncSession, resource_type: str, resource_id: object,
        owner_id: uuid.UUID | None, equipment_id: uuid.UUID | None, user_id: uuid.UUID,
    ) -> bool:
        return await self._linked(session, resource_type, resource_id, owner_id, equipment_id,
                                  user_id, SharePermission.VIEW.value)

    async def can_edit_linked(
        self, session: AsyncSession, resource_type: str, resource_id: object,
        owner_id: uuid.UUID | None, equipment_id: uuid.UUID | None, user_id: uuid.UUID,
    ) -> bool:
        return await self._linked(session, resource_type, resource_id, owner_id, equipment_id,
                                  user_id, SharePermission.EDIT.value)


access_policy = AccessPolicy()
