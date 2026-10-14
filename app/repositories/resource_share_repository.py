import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SharePermission, SharePrincipalType
from app.models.resource_share import ResourceShare


class ResourceShareRepository:
    async def find_by_id(self, session: AsyncSession, share_id: uuid.UUID) -> ResourceShare | None:
        result = await session.execute(select(ResourceShare).where(ResourceShare.share_id == share_id))
        return result.scalar_one_or_none()

    async def find_for_resource(
        self, session: AsyncSession, resource_type: str, resource_id: str
    ) -> list[ResourceShare]:
        result = await session.execute(
            select(ResourceShare)
            .where(ResourceShare.resource_type == resource_type, ResourceShare.resource_id == resource_id)
            .order_by(ResourceShare.created_at)
        )
        return list(result.scalars().all())

    async def find_for_resources(
        self, session: AsyncSession, resource_type: str, resource_ids: list[str]
    ) -> dict[str, list[ResourceShare]]:
        """Shares for many resources in one query (keeps list endpoints O(1) queries)."""
        grouped: dict[str, list[ResourceShare]] = defaultdict(list)
        if not resource_ids:
            return grouped
        result = await session.execute(
            select(ResourceShare).where(
                ResourceShare.resource_type == resource_type,
                ResourceShare.resource_id.in_(resource_ids),
            )
        )
        for share in result.scalars().all():
            grouped[share.resource_id].append(share)
        return grouped

    async def has_permission(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_id: str,
        principals: list[str],
        permission: str,
    ) -> bool:
        if not principals:
            return False
        conditions = [
            ResourceShare.resource_type == resource_type,
            ResourceShare.resource_id == resource_id,
            ResourceShare.principal_id.in_(principals),
        ]
        if permission == SharePermission.EDIT.value:
            conditions.append(ResourceShare.permission == SharePermission.EDIT.value)
        result = await session.execute(select(ResourceShare.share_id).where(*conditions).limit(1))
        return result.scalar_one_or_none() is not None

    async def grant(
        self,
        session: AsyncSession,
        *,
        resource_type: str,
        resource_id: str,
        principal_type: str,
        principal_id: str,
        permission: str,
        granted_by: uuid.UUID | None,
    ) -> ResourceShare:
        """Create or update a share (one row per resource/principal). Commits."""
        stmt = (
            pg_insert(ResourceShare)
            .values(
                resource_type=resource_type,
                resource_id=resource_id,
                principal_type=principal_type,
                principal_id=principal_id,
                permission=permission,
                granted_by=granted_by,
            )
            .on_conflict_do_update(
                constraint="uq_resource_shares_principal",
                set_={"permission": permission, "granted_by": granted_by},
            )
            .returning(ResourceShare)
        )
        share = (await session.execute(stmt)).scalar_one()
        await session.commit()
        return share

    async def set_permission(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_id: str,
        principal_type: str,
        principal_id: str,
        permission: str,
    ) -> bool:
        """Change the permission of an existing share only. Commits."""
        result = await session.execute(
            update(ResourceShare)
            .where(
                ResourceShare.resource_type == resource_type,
                ResourceShare.resource_id == resource_id,
                ResourceShare.principal_type == principal_type,
                ResourceShare.principal_id == principal_id,
            )
            .values(permission=permission)
        )
        await session.commit()
        return result.rowcount > 0

    async def revoke(self, session: AsyncSession, share_id: uuid.UUID) -> bool:
        result = await session.execute(delete(ResourceShare).where(ResourceShare.share_id == share_id))
        await session.commit()
        return result.rowcount > 0

    async def revoke_principal(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_id: str,
        principal_type: str,
        principal_id: str,
    ) -> int:
        result = await session.execute(
            delete(ResourceShare).where(
                ResourceShare.resource_type == resource_type,
                ResourceShare.resource_id == resource_id,
                ResourceShare.principal_type == principal_type,
                ResourceShare.principal_id == principal_id,
            )
        )
        await session.commit()
        return result.rowcount

    async def delete_for_resource(self, session: AsyncSession, resource_type: str, resource_id: str) -> int:
        """Caller commits."""
        result = await session.execute(
            delete(ResourceShare).where(
                ResourceShare.resource_type == resource_type, ResourceShare.resource_id == resource_id
            )
        )
        return result.rowcount

    async def delete_for_resources_owned_by(self, session: AsyncSession, owner_id: uuid.UUID) -> int:
        """Drop grants on every resource the user owns (their rows cascade on
        delete, but resource_shares has no FK to them). Caller commits."""
        from sqlalchemy import String, cast, or_, select

        from app.models.equipment import Equipment
        from app.models.flow_recipe import FlowRecipe
        from app.models.job import Job
        from app.models.module import Module
        from app.models.process_recipe import ProcessRecipe
        from app.models.simulator import Simulator

        owned = (
            ("equipment", select(cast(Equipment.equipment_id, String)).where(Equipment.owner_id == owner_id)),
            ("simulator", select(cast(Simulator.simulator_id, String)).where(Simulator.owner_id == owner_id)),
            ("job", select(cast(Job.job_id, String)).where(Job.user_id == owner_id)),
            ("flow_recipe", select(cast(FlowRecipe.flow_recipe_id, String)).where(FlowRecipe.owner_id == owner_id)),
            ("process_recipe", select(cast(ProcessRecipe.process_recipe_id, String)).where(ProcessRecipe.owner_id == owner_id)),
            ("module", select(cast(Module.module_id, String)).where(Module.owner_id == owner_id)),
        )
        result = await session.execute(
            delete(ResourceShare).where(or_(*[
                (ResourceShare.resource_type == rtype) & ResourceShare.resource_id.in_(ids)
                for rtype, ids in owned
            ]))
        )
        return result.rowcount

    async def delete_for_principal(self, session: AsyncSession, principal_type: str, principal_id: str) -> int:
        """Caller commits. Used when a group or user disappears."""
        result = await session.execute(
            delete(ResourceShare).where(
                ResourceShare.principal_type == principal_type, ResourceShare.principal_id == principal_id
            )
        )
        return result.rowcount

    def _list_filters(self, *, public_only: bool, resource_type: str | None):
        conditions = []
        if public_only:
            conditions.append(ResourceShare.principal_type == SharePrincipalType.PUBLIC.value)
        if resource_type:
            conditions.append(ResourceShare.resource_type == resource_type)
        return conditions

    async def list_all(
        self,
        session: AsyncSession,
        *,
        public_only: bool = False,
        resource_type: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ResourceShare]:
        result = await session.execute(
            select(ResourceShare)
            .where(*self._list_filters(public_only=public_only, resource_type=resource_type))
            .order_by(ResourceShare.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(
        self, session: AsyncSession, *, public_only: bool = False, resource_type: str | None = None
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(ResourceShare)
            .where(*self._list_filters(public_only=public_only, resource_type=resource_type))
        )
        return result.scalar_one()
