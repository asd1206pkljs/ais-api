import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import GroupRole, SharePrincipalType, UserStatus
from app.enums import audit_action as act
from app.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.repositories.group_repository import GroupRepository
from app.repositories.resource_share_repository import ResourceShareRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationMeta
from app.schemas.group import (
    GroupCreate,
    GroupDetail,
    GroupMemberAdd,
    GroupMemberRead,
    GroupMembership,
    GroupRead,
    GroupUpdate,
)
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


class GroupService:
    def __init__(
        self,
        repo: GroupRepository | None = None,
        user_repo: UserRepository | None = None,
        share_repo: ResourceShareRepository | None = None,
        access: AccessPolicy = access_policy,
        audit_svc: AuditService = audit,
    ):
        self._repo = repo or GroupRepository()
        self._users = user_repo or UserRepository()
        self._shares = share_repo or ResourceShareRepository()
        self._access = access
        self._audit = audit_svc

    # --- helpers -----------------------------------------------------------

    async def _load(self, session: AsyncSession, group_id: uuid.UUID):
        group = await self._repo.find_by_id(session, group_id)
        if group is None:
            raise NotFoundError("Group", str(group_id))
        return group

    async def _require_group_admin(self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
        if await self._access.is_admin(session, user_id):
            return
        member = await self._repo.find_member(session, group_id, user_id)
        if member is None or member.role != GroupRole.ADMIN.value:
            raise AuthorizationError("Group admin role required")

    async def _require_member(self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
        if await self._access.is_admin(session, user_id):
            return
        if await self._repo.find_member(session, group_id, user_id) is None:
            raise AuthorizationError("Not a member of this group")

    async def _read(self, session: AsyncSession, group, my_role: str | None = None) -> GroupRead:
        counts = await self._repo.member_counts(session, [group.group_id])
        return GroupRead(
            group_id=group.group_id,
            group_name=group.group_name,
            description=group.description,
            created_at=group.created_at,
            member_count=counts.get(group.group_id, 0),
            my_role=my_role,
        )

    # --- groups ------------------------------------------------------------

    async def create(self, session: AsyncSession, user_id: uuid.UUID, data: GroupCreate) -> GroupRead:
        group = await self._repo.create(session, {
            "group_name": data.group_name,
            "description": data.description,
            "created_by": user_id,
        })
        await self._repo.add_member(session, group.group_id, user_id, GroupRole.ADMIN.value, user_id)
        await self._audit.record(session, act.GROUP_CREATED, resource_type="group",
                                 resource_id=group.group_id, details={"group_name": group.group_name})
        return await self._read(session, group, GroupRole.ADMIN.value)

    async def list_mine(self, session: AsyncSession, user_id: uuid.UUID) -> list[GroupRead]:
        rows = await self._repo.find_for_user(session, user_id)
        counts = await self._repo.member_counts(session, [g.group_id for g, _ in rows])
        return [
            GroupRead(
                group_id=g.group_id, group_name=g.group_name, description=g.description,
                created_at=g.created_at, member_count=counts.get(g.group_id, 0), my_role=m.role,
            )
            for g, m in rows
        ]

    async def memberships(self, session: AsyncSession, user_id: uuid.UUID) -> list[GroupMembership]:
        return [
            GroupMembership(group_id=g.group_id, group_name=g.group_name, role=m.role)
            for g, m in await self._repo.find_for_user(session, user_id)
        ]

    async def list_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> tuple[list[GroupRead], PaginationMeta]:
        groups = await self._repo.find_all(session, skip, limit)
        counts = await self._repo.member_counts(session, [g.group_id for g in groups])
        items = [
            GroupRead(group_id=g.group_id, group_name=g.group_name, description=g.description,
                      created_at=g.created_at, member_count=counts.get(g.group_id, 0))
            for g in groups
        ]
        return items, _meta(await self._repo.count(session), skip, limit)

    async def get(self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupDetail:
        group = await self._load(session, group_id)
        await self._require_member(session, group_id, user_id)
        members = await self._repo.list_members(session, group_id)
        me = next((m.role for m, u in members if u.user_id == user_id), None)
        return GroupDetail(
            group_id=group.group_id,
            group_name=group.group_name,
            description=group.description,
            created_at=group.created_at,
            member_count=len(members),
            my_role=me,
            members=[
                GroupMemberRead(user_id=u.user_id, user_email=u.user_email, user_name=u.user_name,
                                role=m.role, added_at=m.added_at)
                for m, u in members
            ],
        )

    async def update(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, data: GroupUpdate
    ) -> GroupRead:
        await self._load(session, group_id)
        await self._require_group_admin(session, group_id, user_id)
        changes = data.model_dump(exclude_none=True)
        group = await self._repo.update(session, group_id, changes)
        await self._audit.record(session, act.GROUP_UPDATED, resource_type="group",
                                 resource_id=group_id, details=changes)
        member = await self._repo.find_member(session, group_id, user_id)
        return await self._read(session, group, member.role if member else None)

    async def delete(self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
        group = await self._load(session, group_id)
        await self._require_group_admin(session, group_id, user_id)
        await self._shares.delete_for_principal(session, SharePrincipalType.GROUP.value, str(group_id))
        await self._repo.delete(session, group_id)
        await session.commit()
        await self._audit.record(session, act.GROUP_DELETED, resource_type="group",
                                 resource_id=group_id, details={"group_name": group.group_name})

    # --- members -----------------------------------------------------------

    async def add_member(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, data: GroupMemberAdd
    ) -> GroupDetail:
        await self._load(session, group_id)
        await self._require_group_admin(session, group_id, user_id)
        target = await self._users.find_by_email(session, data.email)
        if target is None or target.status != UserStatus.ACTIVE.value:
            # Same message either way: group admins must not learn which emails exist.
            raise ValidationError("No active account with that email")
        if await self._repo.find_member(session, group_id, target.user_id) is not None:
            raise ConflictError("Already a member of this group")
        await self._repo.add_member(session, group_id, target.user_id, data.role.value, user_id)
        await self._audit.record(session, act.GROUP_MEMBER_ADDED, resource_type="group",
                                 resource_id=group_id, target_user_id=target.user_id,
                                 details={"role": data.role.value})
        return await self.get(session, group_id, user_id)

    async def update_member(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID,
        member_id: uuid.UUID, role: GroupRole,
    ) -> GroupDetail:
        await self._load(session, group_id)
        await self._require_group_admin(session, group_id, user_id)
        member = await self._repo.find_member(session, group_id, member_id)
        if member is None:
            raise NotFoundError("GroupMember", str(member_id))
        if member.role == GroupRole.ADMIN.value and role != GroupRole.ADMIN:
            await self._ensure_not_last_admin(session, group_id)
        await self._repo.update_member_role(session, group_id, member_id, role.value)
        await self._audit.record(session, act.GROUP_MEMBER_UPDATED, resource_type="group",
                                 resource_id=group_id, target_user_id=member_id,
                                 details={"role": role.value})
        return await self.get(session, group_id, user_id)

    async def remove_member(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, member_id: uuid.UUID
    ) -> None:
        await self._load(session, group_id)
        if member_id != user_id:  # leaving is always allowed; removing others needs admin
            await self._require_group_admin(session, group_id, user_id)
        member = await self._repo.find_member(session, group_id, member_id)
        if member is None:
            raise NotFoundError("GroupMember", str(member_id))
        if member.role == GroupRole.ADMIN.value:
            await self._ensure_not_last_admin(session, group_id)
        await self._repo.remove_member(session, group_id, member_id)
        await self._audit.record(session, act.GROUP_MEMBER_REMOVED, resource_type="group",
                                 resource_id=group_id, target_user_id=member_id)

    async def _ensure_not_last_admin(self, session: AsyncSession, group_id: uuid.UUID) -> None:
        if await self._repo.count_admins(session, group_id) <= 1:
            raise ConflictError("A group must keep at least one admin")
