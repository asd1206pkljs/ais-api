from pydantic import BaseModel, EmailStr, Field


class ContactRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    company: str = Field(..., min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=100)
    inquiry_type: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=5000)
    consent: bool = Field(...)


class ContactResponse(BaseModel):
    message: str
