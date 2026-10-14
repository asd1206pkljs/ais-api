import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import ModuleType, SaveStatus


class ModuleCreate(BaseModel):
    module_name: str = Field(..., min_length=1, max_length=255)
    module_type: ModuleType
    module_subtype: list[str] = Field(default_factory=list)
    save_status: SaveStatus = SaveStatus.TEMPORARY


class ModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    module_id: int
    module_name: str
    module_type: ModuleType
    module_subtype: list[str]
    owner_id: uuid.UUID | None = None
    equipment_id: uuid.UUID | None = None
    save_status: SaveStatus
    created_at: datetime
    updated_at: datetime


class ModuleUpdate(BaseModel):
    module_name: str | None = Field(None, min_length=1, max_length=255)
    module_type: ModuleType | None = None
    module_subtype: list[str] | None = None
    save_status: SaveStatus | None = None
