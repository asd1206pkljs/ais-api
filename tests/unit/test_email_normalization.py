import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.password_reset import ForgotPasswordRequest
from app.schemas.user import UserCreate
from app.validators.email import normalize_email


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_normalize_email_passes_through_non_strings():
    assert normalize_email(None) is None


def test_register_request_normalizes_email():
    r = RegisterRequest(user_name="Test", email="User@Example.COM", password="Password123!")
    assert r.email == "user@example.com"


def test_login_request_normalizes_email():
    r = LoginRequest(email="  MiXeD@Case.io  ", password="pw")
    assert r.email == "mixed@case.io"


def test_user_create_normalizes_email():
    u = UserCreate(user_name="Test", user_email="ABC@Domain.COM", user_password="Password123!")
    assert u.user_email == "abc@domain.com"


def test_forgot_password_request_normalizes_email():
    r = ForgotPasswordRequest(email="Reset@Me.COM")
    assert r.email == "reset@me.com"


def test_normalized_email_still_rejects_invalid_format():
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="pw")


def test_resend_verification_request_normalizes_email():
    from app.schemas.auth import ResendVerificationRequest

    r = ResendVerificationRequest(email="  Pending@Example.COM ")
    assert r.email == "pending@example.com"
