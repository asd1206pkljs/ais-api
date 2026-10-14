import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: int
    occurred_at: datetime
    actor_id: uuid.UUID | None
    actor_email: str | None
    actor_type: str
    action: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    target_user_id: uuid.UUID | None
    ip_address: str | None
    request_id: str | None
    details: dict | None
