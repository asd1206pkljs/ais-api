import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.validators.password import validate_strong_password


class UserCreate(BaseModel):
    user_name: str = Field(..., min_length=1, max_length=255)
    user_email: EmailStr
    user_password: str = Field(..., min_length=8)
    user_company: str | None = Field(None, max_length=255)

    @field_validator("user_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return validate_strong_password(v)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    user_name: str
    user_email: str
    user_company: str | None
    user_credits: int
    joined_at: datetime
    last_login_at: datetime | None


class UserUpdate(BaseModel):
    user_name: str | None = Field(None, min_length=1, max_length=255)
    user_password: str | None = Field(None, min_length=8)
    user_company: str | None = Field(None, max_length=255)

    @field_validator("user_password")
    @classmethod
    def _password_strength(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_strong_password(v)


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return validate_strong_password(v)


class CreditPurchase(BaseModel):
    quantity: int = Field(1, ge=1, le=100)
    payment_token: str | None = Field(None, max_length=512)


class CreditRequest(BaseModel):
    requested_amount: int = Field(..., ge=1, le=10000)
    reason: str | None = Field(None, max_length=1000)


class CreditTransactionResult(BaseModel):
    user_credits: int
    added: int
    total_paid_krw: int
