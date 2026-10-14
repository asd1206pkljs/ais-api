"""SQL building blocks for "which rows may this user see" queries.

`principals` is the set of principal ids that stand for a user: their own id,
every group they belong to, and "*" (public). A resource is accessible when
the user owns it or a resource_shares row names one of those principals.
"""
from sqlalchemy import String, cast, exists, select

from app.enums import SharePermission
from app.models.equipment import Equipment
from app.models.resource_share import ResourceShare


def shared_with(id_column, resource_type: str, principals: list[str], permission: str | None = None):
    """EXISTS clause: a share on `resource_type`/`id_column` for any of `principals`."""
    conditions = [
        ResourceShare.resource_type == resource_type,
        ResourceShare.resource_id == cast(id_column, String),
        ResourceShare.principal_id.in_(principals or ["-"]),
    ]
    if permission == SharePermission.EDIT.value:
        conditions.append(ResourceShare.permission == SharePermission.EDIT.value)
    return exists(select(ResourceShare.share_id).where(*conditions))


def accessible_equipment_ids(user_id, principals: list[str], permission: str | None = None):
    """Subquery of equipment ids the user owns or was granted."""
    return (
        select(Equipment.equipment_id)
        .where(
            Equipment.save_status != "deleted",
            (Equipment.owner_id == user_id)
            | shared_with(Equipment.equipment_id, "equipment", principals, permission),
        )
        .scalar_subquery()
    )
