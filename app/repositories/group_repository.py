import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import GroupRole
from app.models.group import Group, GroupMember
from app.models.user import User


class GroupRepository:
    async def create(self, session: AsyncSession, data: dict) -> Group:
        group = Group(**data)
        session.add(group)
        await session.commit()
        await session.refresh(group)
        return group

    async def find_by_id(self, session: AsyncSession, group_id: uuid.UUID) -> Group | None:
        result = await session.execute(select(Group).where(Group.group_id == group_id))
        return result.scalar_one_or_none()

    async def update(self, session: AsyncSession, group_id: uuid.UUID, data: dict) -> Group | None:
        group = await self.find_by_id(session, group_id)
        if group is None:
            return None
        for key, value in data.items():
            setattr(group, key, value)
        await session.commit()
        await session.refresh(group)
        return group

    async def delete(self, session: AsyncSession, group_id: uuid.UUID) -> bool:
        """Caller commits (shares referencing the group are removed by the service)."""
        result = await session.execute(delete(Group).where(Group.group_id == group_id))
        return result.rowcount > 0

    async def find_all(self, session: AsyncSession, skip: int = 0, limit: int = 100) -> list[Group]:
        result = await session.execute(
            select(Group).order_by(Group.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count(self, session: AsyncSession) -> int:
        return (await session.execute(select(func.count()).select_from(Group))).scalar_one()

    async def find_for_user(self, session: AsyncSession, user_id: uuid.UUID) -> list[tuple[Group, GroupMember]]:
        result = await session.execute(
            select(Group, GroupMember)
            .join(GroupMember, GroupMember.group_id == Group.group_id)
            .where(GroupMember.user_id == user_id)
            .order_by(Group.group_name)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def member_group_ids(self, session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
        result = await session.execute(
            select(GroupMember.group_id).where(GroupMember.user_id == user_id)
        )
        return list(result.scalars().all())

    async def find_member(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMember | None:
        result = await session.execute(
            select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_members(
        self, session: AsyncSession, group_id: uuid.UUID
    ) -> list[tuple[GroupMember, User]]:
        result = await session.execute(
            select(GroupMember, User)
            .join(User, User.user_id == GroupMember.user_id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.added_at)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def member_counts(self, session: AsyncSession, group_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not group_ids:
            return {}
        result = await session.execute(
            select(GroupMember.group_id, func.count())
            .where(GroupMember.group_id.in_(group_ids))
            .group_by(GroupMember.group_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def add_member(
        self,
        session: AsyncSession,
        group_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        added_by: uuid.UUID | None,
    ) -> GroupMember:
        member = GroupMember(group_id=group_id, user_id=user_id, role=role, added_by=added_by)
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member

    async def update_member_role(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, role: str
    ) -> bool:
        result = await session.execute(
            update(GroupMember)
            .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            .values(role=role)
        )
        await session.commit()
        return result.rowcount > 0

    async def remove_member(self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await session.execute(
            delete(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        )
        await session.commit()
        return result.rowcount > 0

    async def count_admins(self, session: AsyncSession, group_id: uuid.UUID) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == group_id, GroupMember.role == GroupRole.ADMIN.value)
        )
        return result.scalar_one()
