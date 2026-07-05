import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import SaveStatus


class FlowRecipeCreate(BaseModel):
    flow_recipe_name: str = Field(..., min_length=1, max_length=255)
    save_status: SaveStatus = SaveStatus.TEMPORARY


class FlowRecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    flow_recipe_id: uuid.UUID
    flow_recipe_name: str
    flow_recipe_path: str
    save_status: SaveStatus
    created_at: datetime
    updated_at: datetime


class FlowRecipeUpdate(BaseModel):
    flow_recipe_name: str | None = Field(None, min_length=1, max_length=255)
    save_status: SaveStatus | None = None
