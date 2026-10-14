from pydantic import BaseModel, Field, field_validator

from app.validators.email import NormalizedEmail
from app.validators.password import validate_strong_password


class ForgotPasswordRequest(BaseModel):
    email: NormalizedEmail


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=2048)
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return validate_strong_password(v)


class MessageResponse(BaseModel):
    message: str
