import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import GroupRole
from app.validators.email import NormalizedEmail


class GroupCreate(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)


class GroupUpdate(BaseModel):
    group_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_id: uuid.UUID
    group_name: str
    description: str | None
    created_at: datetime
    member_count: int = 0
    my_role: GroupRole | None = None


class GroupMemberRead(BaseModel):
    user_id: uuid.UUID
    user_email: str
    user_name: str
    role: GroupRole
    added_at: datetime


class GroupDetail(GroupRead):
    members: list[GroupMemberRead] = []


class GroupMemberAdd(BaseModel):
    email: NormalizedEmail
    role: GroupRole = GroupRole.MEMBER


class GroupMemberUpdate(BaseModel):
    role: GroupRole


class GroupMembership(BaseModel):
    group_id: uuid.UUID
    group_name: str
    role: GroupRole


class PermissionsRead(BaseModel):
    """What the signed-in user may do: platform role plus group memberships."""

    user_id: uuid.UUID
    role: str
    is_admin: bool
    status: str
    groups: list[GroupMembership]
    consent_up_to_date: bool
