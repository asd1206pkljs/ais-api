from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConsentInput(BaseModel):
    """Versions of the legal documents the user accepted (must match current)."""

    terms_version: str = Field(..., min_length=1, max_length=64)
    privacy_version: str = Field(..., min_length=1, max_length=64)


class ConsentRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document: str
    version: str
    accepted_at: datetime


class ConsentStatus(BaseModel):
    terms_version: str
    privacy_version: str
    accepted_terms_version: str | None = None
    accepted_privacy_version: str | None = None
    up_to_date: bool


class LegalVersions(BaseModel):
    terms_version: str
    privacy_version: str
    consent_required: bool
