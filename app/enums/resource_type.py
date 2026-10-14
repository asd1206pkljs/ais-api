from enum import Enum


class ResourceType(str, Enum):
    """Shareable resource kinds (resource_shares.resource_type)."""

    EQUIPMENT = "equipment"
    SIMULATOR = "simulator"
    JOB = "job"
    FLOW_RECIPE = "flow_recipe"
    PROCESS_RECIPE = "process_recipe"
    MODULE = "module"
