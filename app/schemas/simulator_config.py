from typing import Any

from pydantic import BaseModel, Field


class SimulatorConfig(BaseModel):
    selected_flow_recipe_ids: list[str] = Field(default_factory=list)
    module_time_configs: dict[str, Any] = Field(default_factory=dict)
