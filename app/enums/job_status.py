from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    TRAINING = "training"
    COMPLETE = "complete"
    FAILED = "failed"
    PAUSED = "paused"
