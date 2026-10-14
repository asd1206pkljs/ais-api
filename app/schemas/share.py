import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.enums import SharePermission, SharePrincipalType
from app.validators.email import NormalizedEmail


class ShareCreate(BaseModel):
    principal_type: SharePrincipalType
    # user: email or user_id; group: group_id; public: nothing.
    email: NormalizedEmail | None = None
    user_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    permission: SharePermission = SharePermission.VIEW

    @model_validator(mode="after")
    def _principal_fields(self):
        if self.principal_type == SharePrincipalType.USER and not (self.email or self.user_id):
            raise ValueError("email or user_id is required for a user share")
        if self.principal_type == SharePrincipalType.GROUP and self.group_id is None:
            raise ValueError("group_id is required for a group share")
        return self


class ShareRead(BaseModel):
    share_id: uuid.UUID
    resource_type: str
    resource_id: str
    principal_type: SharePrincipalType
    principal_id: str
    # Human-readable target: user email, group name, or "public".
    principal_label: str
    permission: SharePermission
    granted_by: uuid.UUID | None
    created_at: datetime


class ShareAdminRead(ShareRead):
    resource_name: str | None = None
    owner_id: uuid.UUID | None = None


class LegacyAccessRequest(BaseModel):
    """Body of the pre-existing /viewers and /editors endpoints."""

    user_id: str = Field(..., description="User ID to grant access to, or '*' (admins only)")
