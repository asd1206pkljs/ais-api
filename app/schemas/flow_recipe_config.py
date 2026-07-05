from pydantic import BaseModel, Field


class ProcessRecipeStep(BaseModel):
    step: int = Field(..., ge=1)
    process_recipe_id: str


class FlowRecipeConfig(BaseModel):
    flow_recipe_name: str = Field(..., min_length=1)
    num_process_steps: int = Field(..., ge=0)
    process_recipe_steps: list[ProcessRecipeStep] = Field(default_factory=list)
    module_sequence: list[list[str]] = Field(default_factory=list)
