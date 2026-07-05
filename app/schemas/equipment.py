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
    equipment_configuration_file_path: str
    owner_id: uuid.UUID
    viewers: list[str]
    editors: list[str]
    save_status: str
    created_at: datetime
    updated_at: datetime


class EquipmentUpdate(BaseModel):
    equipment_name: str | None = Field(None, min_length=1, max_length=255)
    save_status: SaveStatus | None = None


class AccessUserRequest(BaseModel):
    user_id: str = Field(..., description="User ID to grant access to")
