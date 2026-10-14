import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SaveStatus = Literal['saved_temporarily', 'complete', 'deleted']


class EquipmentCreate(BaseModel):
    equipment_name: str = Field(..., min_length=1, max_length=255)


class EquipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    equipment_id: uuid.UUID
    equipment_name: str
    owner_id: uuid.UUID
    # Principal ids (users, groups, or "*") with view / edit access. Derived
    # from resource_shares; kept so existing clients can compute canEdit.
    viewers: list[str] = []
    editors: list[str] = []
    save_status: str
    created_at: datetime
    updated_at: datetime


class EquipmentUpdate(BaseModel):
    equipment_name: str | None = Field(None, min_length=1, max_length=255)
    save_status: SaveStatus | None = None


class AccessUserRequest(BaseModel):
    user_id: str = Field(..., description="User ID to grant access to")
