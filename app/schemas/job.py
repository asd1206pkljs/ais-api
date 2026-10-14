import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import JobStatus


class JobCreate(BaseModel):
    simulator_id: uuid.UUID
    job_name: str = Field(..., min_length=1, max_length=255)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: int
    user_id: uuid.UUID
    # Owner email — populated only for admin listings so admins can identify
    # the owner of each job; None for regular (owner/viewer) listings.
    user_email: str | None = None
    simulator_id: uuid.UUID
    job_name: str
    job_status: JobStatus
    viewers: list[str] = []
    created_at: datetime
    updated_at: datetime


class JobUpdate(BaseModel):
    # Status is never set by the owner: only request-cancel/resume and the
    # training servers (internal API) move a job between states.
    job_name: str | None = Field(None, min_length=1, max_length=255)


class JobAdminRead(BaseModel):
    """Job listing payload for internal admin tooling — exposes the user's
    email so the operator running the launcher can identify the owner."""

    model_config = ConfigDict(from_attributes=True)

    job_id: int
    user_id: uuid.UUID
    user_email: str
    simulator_id: uuid.UUID
    job_name: str
    job_status: JobStatus
    claimed_by: str | None = None
    result_path: str | None = None
    created_at: datetime
    updated_at: datetime


class JobStatusUpdate(BaseModel):
    job_status: JobStatus


class JobClaimRequest(BaseModel):
    claimed_by: str = Field(..., min_length=1, max_length=255,
                            description="Claiming server id (AIS_SERVER_ID or hostname)")


class JobAccessUserRequest(BaseModel):
    user_id: str = Field(..., description="User ID to grant access to")
