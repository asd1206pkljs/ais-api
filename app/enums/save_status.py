from enum import Enum


class SaveStatus(str, Enum):
    COMPLETE = "complete"
    TEMPORARY = "temporary"
