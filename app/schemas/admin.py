import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.enums import UserRole, UserStatus
from app.schemas.group import GroupMembership


class AdminUserRead(BaseModel):
    """Account metadata for the admin console. Never carries resource content."""

    user_id: uuid.UUID
    user_name: str
    user_email: str
    user_company: str | None
    user_credits: int
    role: UserRole
    status: UserStatus
    approved: bool
    joined_at: datetime
    last_login_at: datetime | None
    groups: list[GroupMembership] = []


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    status: UserStatus | None = None
    note: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def _something_to_change(self):
        if self.role is None and self.status is None:
            raise ValueError("role or status is required")
        return self


class CreditAdjustment(BaseModel):
    amount: int = Field(..., ge=-10000, le=10000, description="Positive adds, negative removes")
    reason: str = Field(..., min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _non_zero(self):
        if self.amount == 0:
            raise ValueError("amount must not be zero")
        return self


class AdminStats(BaseModel):
    users_total: int
    users_pending_approval: int
    requests_pending: int
    public_shares: int
