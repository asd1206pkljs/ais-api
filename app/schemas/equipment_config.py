from typing import Any

from pydantic import BaseModel, Field


class ModuleClusterEntry(BaseModel):
    module_id: int
    module_type: str = Field(default="")
    display_name: str = Field(default="")
    cluster: list[str] = Field(..., min_length=1)


class TimeConfig(BaseModel):
    """단일 시간 값 설정. fixedTime(초) 또는 useTimeTable=True."""
    useTimeTable: bool = False
    fixedTime: str = ""


class AlignerTimeConfig(BaseModel):
    """aligner timetable.
    alignTime: {loadlock_module_id(str): TimeConfig}
      - 키는 loadlock의 module_id (str)
      - 값은 해당 loadlock으로 align할 때의 시간 설정
    """
    alignTime: dict[str, TimeConfig] = Field(default_factory=dict)
    hasDoor: bool = False
    door: TimeConfig | None = None


class EquipmentConfig(BaseModel):
    equipment_name: str = Field(..., min_length=1)
    cluster_type: str = Field(..., pattern="^(single_cluster|dual_cluster)$")
    modules: list[ModuleClusterEntry] = Field(default_factory=list)
    timetables: dict[str, Any] = Field(default_factory=dict)
    flow_recipe_ids: list[str] = Field(default_factory=list)
    process_recipe_ids: list[str] = Field(default_factory=list)
