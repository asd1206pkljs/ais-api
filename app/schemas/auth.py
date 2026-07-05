from pydantic import BaseModel, EmailStr, Field, field_validator

from app.validators.password import validate_strong_password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    user_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    company: str | None = Field(None, max_length=255)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return validate_strong_password(v)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
