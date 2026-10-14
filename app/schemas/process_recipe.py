import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import SaveStatus


class ProcessRecipeCreate(BaseModel):
    process_recipe_name: str = Field(..., min_length=1, max_length=255)
    save_status: SaveStatus = SaveStatus.TEMPORARY


class ProcessRecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    process_recipe_id: uuid.UUID
    process_recipe_name: str
    owner_id: uuid.UUID | None = None
    equipment_id: uuid.UUID | None = None
    save_status: SaveStatus
    created_at: datetime
    updated_at: datetime


class ProcessRecipeUpdate(BaseModel):
    process_recipe_name: str | None = Field(None, min_length=1, max_length=255)
    save_status: SaveStatus | None = None
