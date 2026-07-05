from enum import Enum


class ModuleType(str, Enum):
    PROCESS_MODULE = "process_module"
    LOADLOCK = "loadlock"
    LOADPORT = "loadport"
    ROBOT = "robot"
    BUFFER = "buffer"
    ALIGNER = "aligner"
