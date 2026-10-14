import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SaveStatus = Literal['saved_temporarily', 'complete', 'deleted']


class SimulatorCreate(BaseModel):
    simulator_name: str = Field(..., min_length=1, max_length=255)


class SimulatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    simulator_id: uuid.UUID
    simulator_name: str
    equipment_id: uuid.UUID | None
    owner_id: uuid.UUID
    viewers: list[str] = []
    editors: list[str] = []
    save_status: str
    created_at: datetime
    updated_at: datetime


class SimulatorUpdate(BaseModel):
    simulator_name: str | None = Field(None, min_length=1, max_length=255)
    equipment_id: uuid.UUID | None = None
    save_status: SaveStatus | None = None


class SimulatorAccessUserRequest(BaseModel):
    user_id: str = Field(..., description="User ID to grant access to")
