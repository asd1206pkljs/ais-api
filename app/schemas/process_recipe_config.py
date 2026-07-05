from pydantic import BaseModel, Field


class ProcessRecipeConfig(BaseModel):
    process_recipe_name: str = Field(..., min_length=1)
    user_added_process_modules: list[int] = Field(default_factory=list)
    process_time: dict[str, float] = Field(default_factory=dict)
