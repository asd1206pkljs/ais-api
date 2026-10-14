"""Resource-level sharing: who may view/edit a resource besides its owner.

Rules (enforced here, not in the UI):
- the owner manages a resource's shares; a platform admin may list and revoke
  them and may publish a resource (public share), but can never grant a user
  or group share on a resource they do not own (that would be a back door to
  the content). The owner is e-mailed when an admin publishes their resource.
- a user share targets an existing active account (by email or id)
- a group share needs the granter to belong to the group
- public ("*") shares are reserved for platform admins
- jobs are read-only to others: only `view` can be granted
"""
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    PUBLIC_PRINCIPAL_ID,
    ResourceType,
    SharePermission,
    SharePrincipalType,
    UserStatus,
)
from app.enums import audit_action as act
from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.models.resource_share import ResourceShare
from app.repositories.group_repository import GroupRepository
from app.repositories.resource_share_repository import ResourceShareRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationMeta
from app.schemas.share import ShareAdminRead, ShareCreate, ShareRead
from app.services import notifications
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit

PUBLIC_LABEL = "public"


@dataclass(frozen=True)
class ResourceInfo:
    resource_type: str
    resource_id: str
    owner_id: uuid.UUID | None
    name: str | None


def _parse_id(resource_type: str, raw: str) -> object:
    if resource_type in (ResourceType.JOB.value, ResourceType.MODULE.value):
        try:
            return int(raw)
        except ValueError:
            raise NotFoundError(resource_type, raw)
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise NotFoundError(resource_type, raw)


async def load_resource(session: AsyncSession, resource_type: str, resource_id: str) -> ResourceInfo:
    """Fetch owner + display name of any shareable resource."""
    from app.repositories.equipment_repository import EquipmentRepository
    from app.repositories.flow_recipe_repository import FlowRecipeRepository
    from app.repositories.job_repository import JobRepository
    from app.repositories.module_repository import ModuleRepository
    from app.repositories.process_recipe_repository import ProcessRecipeRepository
    from app.repositories.simulator_repository import SimulatorRepository

    registry = {
        ResourceType.EQUIPMENT.value: (EquipmentRepository, "owner_id", "equipment_name"),
        ResourceType.SIMULATOR.value: (SimulatorRepository, "owner_id", "simulator_name"),
        ResourceType.JOB.value: (JobRepository, "user_id", "job_name"),
        ResourceType.FLOW_RECIPE.value: (FlowRecipeRepository, "owner_id", "flow_recipe_name"),
        ResourceType.PROCESS_RECIPE.value: (ProcessRecipeRepository, "owner_id", "process_recipe_name"),
        ResourceType.MODULE.value: (ModuleRepository, "owner_id", "module_name"),
    }
    if resource_type not in registry:
        raise ValidationError(f"Unknown resource type: {resource_type}")
    repo_cls, owner_attr, name_attr = registry[resource_type]
    row = await repo_cls().find_by_id(session, _parse_id(resource_type, resource_id))
    if row is None or getattr(row, "save_status", None) == "deleted":
        raise NotFoundError(resource_type, resource_id)
    return ResourceInfo(resource_type, str(resource_id), getattr(row, owner_attr), getattr(row, name_attr))


class SharingService:
    def __init__(
        self,
        share_repo: ResourceShareRepository | None = None,
        group_repo: GroupRepository | None = None,
        user_repo: UserRepository | None = None,
        access: AccessPolicy = access_policy,
        audit_svc: AuditService = audit,
    ):
        self._shares = share_repo or ResourceShareRepository()
        self._groups = group_repo or GroupRepository()
        self._users = user_repo or UserRepository()
        self._access = access
        self._audit = audit_svc

    # --- labels ---------------------------------------------------------------

    async def _labels(self, session: AsyncSession, shares: list[ResourceShare]) -> dict[str, str]:
        user_ids, group_ids = [], []
        for s in shares:
            if s.principal_type == SharePrincipalType.USER.value:
                user_ids.append(uuid.UUID(s.principal_id))
            elif s.principal_type == SharePrincipalType.GROUP.value:
                group_ids.append(uuid.UUID(s.principal_id))
        labels: dict[str, str] = {PUBLIC_PRINCIPAL_ID: PUBLIC_LABEL}
        users = await self._users.find_many_by_ids(session, user_ids)
        labels.update({str(uid): u.user_email for uid, u in users.items()})
        for gid in group_ids:
            group = await self._groups.find_by_id(session, gid)
            labels[str(gid)] = group.group_name if group else "(deleted group)"
        return labels

    @staticmethod
    def _to_read(share: ResourceShare, label: str) -> ShareRead:
        return ShareRead(
            share_id=share.share_id,
            resource_type=share.resource_type,
            resource_id=share.resource_id,
            principal_type=share.principal_type,
            principal_id=share.principal_id,
            principal_label=label,
            permission=share.permission,
            granted_by=share.granted_by,
            created_at=share.created_at,
        )

    async def _reads(self, session: AsyncSession, shares: list[ResourceShare]) -> list[ShareRead]:
        labels = await self._labels(session, shares)
        return [self._to_read(s, labels.get(s.principal_id, s.principal_id)) for s in shares]

    # --- legacy viewers/editors lists ---------------------------------------------

    async def access_lists(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_ids: list[str],
        *,
        viewer_id: uuid.UUID | None = None,
        owners: dict[str, uuid.UUID | None] | None = None,
    ) -> dict[str, tuple[list[str], list[str]]]:
        """(viewers, editors) per resource, one query for all ids.

        The owner of a resource gets the full principal lists. Anyone else only
        learns about their *own* effective access: their user id appears in
        viewers/editors when a user, group or public share grants it, and "*"
        is kept so clients can tell a public resource apart. Other users' ids
        are never exposed to non-owners.
        """
        grouped = await self._shares.find_for_resources(session, resource_type, resource_ids)
        mine: set[str] = set()
        if viewer_id is not None:
            mine = set(await self._access.principals(session, viewer_id))
        out: dict[str, tuple[list[str], list[str]]] = {}
        for rid in resource_ids:
            shares = grouped.get(rid, [])
            is_owner = viewer_id is not None and (owners or {}).get(rid) == viewer_id
            if is_owner or viewer_id is None:
                viewers = [s.principal_id for s in shares]
                editors = [s.principal_id for s in shares if s.permission == SharePermission.EDIT.value]
            else:
                uid = str(viewer_id)
                relevant = [s for s in shares if s.principal_id in mine]
                viewers = [uid] if relevant else []
                editors = [uid] if any(s.permission == SharePermission.EDIT.value for s in relevant) else []
                public = [s for s in relevant if s.principal_id == PUBLIC_PRINCIPAL_ID]
                if public:
                    viewers.append(PUBLIC_PRINCIPAL_ID)
                    if public[0].permission == SharePermission.EDIT.value:
                        editors.append(PUBLIC_PRINCIPAL_ID)
            out[rid] = (viewers, editors)
        return out

    # --- management ------------------------------------------------------------

    async def _require_manager(self, session: AsyncSession, info: ResourceInfo, user_id: uuid.UUID) -> bool:
        """Owner or platform admin. Returns whether the caller is an admin."""
        admin = await self._access.is_admin(session, user_id)
        if not admin and not self._access.is_owner(info.owner_id, user_id):
            raise AuthorizationError("Only the owner can manage sharing")
        return admin

    async def list_shares(
        self, session: AsyncSession, resource_type: str, resource_id: str, user_id: uuid.UUID
    ) -> list[ShareRead]:
        info = await load_resource(session, resource_type, resource_id)
        await self._require_manager(session, info, user_id)
        return await self._reads(session, await self._shares.find_for_resource(session, resource_type, info.resource_id))

    async def _resolve_principal(
        self, session: AsyncSession, info: ResourceInfo, user_id: uuid.UUID, data: ShareCreate, is_admin: bool
    ) -> tuple[str, str]:
        if data.principal_type == SharePrincipalType.PUBLIC:
            if not is_admin:
                raise AuthorizationError("Public sharing requires a platform administrator")
            return SharePrincipalType.PUBLIC.value, PUBLIC_PRINCIPAL_ID
        if not self._access.is_owner(info.owner_id, user_id):
            raise AuthorizationError("Only the owner can share with users or groups")
        if data.principal_type == SharePrincipalType.GROUP:
            group = await self._groups.find_by_id(session, data.group_id)
            if group is None:
                raise NotFoundError("Group", str(data.group_id))
            if await self._groups.find_member(session, group.group_id, user_id) is None:
                raise AuthorizationError("You can only share with groups you belong to")
            return SharePrincipalType.GROUP.value, str(group.group_id)
        target = None
        if data.user_id is not None:
            target = await self._users.find_by_id(session, data.user_id)
        elif data.email:
            target = await self._users.find_by_email(session, data.email)
        if target is None or not target.approved or target.status != UserStatus.ACTIVE.value:
            raise ValidationError("No active account matches that user")
        if target.user_id == info.owner_id:
            raise ValidationError("The owner already has full access")
        return SharePrincipalType.USER.value, str(target.user_id)

    async def grant(
        self, session: AsyncSession, resource_type: str, resource_id: str, user_id: uuid.UUID, data: ShareCreate
    ) -> ShareRead:
        info = await load_resource(session, resource_type, resource_id)
        is_admin = await self._require_manager(session, info, user_id)
        if resource_type == ResourceType.JOB.value and data.permission != SharePermission.VIEW:
            raise ValidationError("Jobs can only be shared for viewing")
        principal_type, principal_id = await self._resolve_principal(session, info, user_id, data, is_admin)
        share = await self._shares.grant(
            session,
            resource_type=resource_type,
            resource_id=info.resource_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=data.permission.value,
            granted_by=user_id,
        )
        await self._audit.record(
            session, act.SHARE_GRANTED, resource_type=resource_type, resource_id=info.resource_id,
            target_user_id=uuid.UUID(principal_id) if principal_type == SharePrincipalType.USER.value else None,
            details={"principal_type": principal_type, "principal_id": principal_id,
                     "permission": data.permission.value, "by_admin": is_admin and info.owner_id != user_id},
        )
        if principal_type == SharePrincipalType.PUBLIC.value and info.owner_id not in (None, user_id):
            owner = await self._users.find_by_id(session, info.owner_id)
            if owner is not None:
                notifications.notify_owner_resource_published(owner.user_email, resource_type, info.name)
        (read,) = await self._reads(session, [share])
        return read

    async def grant_legacy(
        self, session: AsyncSession, resource_type: str, resource_id: str, user_id: uuid.UUID,
        principal: str, permission: SharePermission,
    ) -> None:
        """Back-compat for POST .../viewers and .../editors bodies ({"user_id": ...} or "*")."""
        if principal == PUBLIC_PRINCIPAL_ID:
            data = ShareCreate(principal_type=SharePrincipalType.PUBLIC, permission=permission)
        else:
            try:
                data = ShareCreate(principal_type=SharePrincipalType.USER,
                                   user_id=uuid.UUID(principal), permission=permission)
            except ValueError:
                raise ValidationError("user_id must be a UUID or '*'")
        await self.grant(session, resource_type, resource_id, user_id, data)

    async def revoke(
        self, session: AsyncSession, resource_type: str, resource_id: str, user_id: uuid.UUID, share_id: uuid.UUID
    ) -> None:
        info = await load_resource(session, resource_type, resource_id)
        await self._require_manager(session, info, user_id)
        share = await self._shares.find_by_id(session, share_id)
        if share is None or share.resource_type != resource_type or share.resource_id != info.resource_id:
            raise NotFoundError("Share", str(share_id))
        await self._shares.revoke(session, share_id)
        await self._audit.record(
            session, act.SHARE_REVOKED, resource_type=resource_type, resource_id=info.resource_id,
            details={"principal_type": share.principal_type, "principal_id": share.principal_id},
        )

    async def revoke_legacy(
        self, session: AsyncSession, resource_type: str, resource_id: str, user_id: uuid.UUID,
        principal: str, permission: SharePermission,
    ) -> None:
        """DELETE .../viewers/{id}: drop the share; DELETE .../editors/{id}: downgrade to view."""
        info = await load_resource(session, resource_type, resource_id)
        await self._require_manager(session, info, user_id)
        ptype = SharePrincipalType.PUBLIC.value if principal == PUBLIC_PRINCIPAL_ID else SharePrincipalType.USER.value
        if permission == SharePermission.VIEW:
            await self._shares.revoke_principal(session, resource_type, info.resource_id, ptype, principal)
        else:
            await self._shares.set_permission(
                session, resource_type, info.resource_id, ptype, principal, SharePermission.VIEW.value
            )
        await self._audit.record(
            session, act.SHARE_REVOKED, resource_type=resource_type, resource_id=info.resource_id,
            details={"principal_type": ptype, "principal_id": principal, "permission": permission.value},
        )

    async def delete_for_resource(self, session: AsyncSession, resource_type: str, resource_id: object) -> None:
        """Called when a resource is deleted. Caller commits."""
        await self._shares.delete_for_resource(session, resource_type, str(resource_id))

    # --- admin overview ---------------------------------------------------------

    async def list_all(
        self, session: AsyncSession, *, public_only: bool, resource_type: str | None, skip: int, limit: int
    ) -> tuple[list[ShareAdminRead], PaginationMeta]:
        shares = await self._shares.list_all(
            session, public_only=public_only, resource_type=resource_type, skip=skip, limit=limit
        )
        total = await self._shares.count_all(session, public_only=public_only, resource_type=resource_type)
        labels = await self._labels(session, shares)
        items = []
        for s in shares:
            try:
                info = await load_resource(session, s.resource_type, s.resource_id)
                name, owner = info.name, info.owner_id
            except NotFoundError:
                name, owner = None, None
            base = self._to_read(s, labels.get(s.principal_id, s.principal_id))
            items.append(ShareAdminRead(**base.model_dump(), resource_name=name, owner_id=owner))
        pages = (total + limit - 1) // limit if limit > 0 else 0
        meta = PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)
        return items, meta

    async def admin_revoke(self, session: AsyncSession, share_id: uuid.UUID) -> None:
        share = await self._shares.find_by_id(session, share_id)
        if share is None:
            raise NotFoundError("Share", str(share_id))
        await self._shares.revoke(session, share_id)
        await self._audit.record(
            session, act.SHARE_REVOKED, resource_type=share.resource_type, resource_id=share.resource_id,
            details={"principal_type": share.principal_type, "principal_id": share.principal_id, "by": "admin"},
        )
