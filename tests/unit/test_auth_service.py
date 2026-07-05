import time
import uuid
from unittest.mock import patch

import pytest

from app.exceptions import AuthenticationError
from app.services.auth_service import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_different_hashes():
    h1 = hash_password("mysecret")
    h2 = hash_password("mysecret")
    assert h1 != h2


def test_verify_password_correct():
    hashed = hash_password("mysecret")
    assert verify_password("mysecret", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("mysecret")
    assert verify_password("wrongpassword", hashed) is False


def test_create_and_decode_token():
    user_id = uuid.uuid4()
    email = "user@example.com"
    token = create_access_token(user_id, email)
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == email


def test_decode_invalid_token():
    with pytest.raises(AuthenticationError):
        decode_access_token("not.a.valid.token")


def test_decode_expired_token():
    with patch("app.services.auth_service.settings") as mock_settings:
        mock_settings.JWT_SECRET_KEY = "test-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.JWT_EXPIRY_MINUTES = -1
        token = create_access_token(uuid.uuid4(), "test@example.com")
    with pytest.raises(AuthenticationError):
        decode_access_token(token)
