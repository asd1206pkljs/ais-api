import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.enums import RequestStatus, RequestType


class RequestRead(BaseModel):
    request_id: uuid.UUID
    user_id: uuid.UUID
    request_type: RequestType
    status: RequestStatus
    payload: dict
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class RequestAdminRead(RequestRead):
    user_email: str
    user_name: str
    decided_by: uuid.UUID | None


class RequestDecision(BaseModel):
    note: str | None = Field(None, max_length=1000)
    # Credit requests only: grant a different amount than requested.
    granted_amount: int | None = Field(None, ge=1, le=10000)
