import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt

from app.config import settings
from app.exceptions import ValidationError
from app.models.user import User
from app.services import password_reset_service as prs
from app.services.password_reset_service import PasswordResetService

SEND = "app.services.password_reset_service.send_password_reset_email"


def _make_user(**kwargs) -> User:
    defaults = {
        "user_id": uuid.uuid4(),
        "user_email": "test@example.com",
        "user_password": "$2b$12$abcdefghijklmnopqrstuvwxyz0123456789",
        "token_version": 2,
        "approved": True,
    }
    defaults.update(kwargs)
    user = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _token(user, *, prefix=None, purpose=prs.PURPOSE, minutes=30) -> str:
    payload = {
        "sub": str(user.user_id),
        "purpose": purpose,
        "pwd_prefix": prefix if prefix is not None else user.user_password[: prs.PWD_PREFIX_LEN],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def throttle():
    return AsyncMock()


@pytest.fixture
def service(repo, throttle):
    return PasswordResetService(repo, throttle)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_request_reset_for_unknown_email_is_silent(service, repo, session):
    # No error and no email: the endpoint must not reveal which emails exist.
    repo.find_by_email.return_value = None
    with patch(SEND) as send:
        await service.request_reset(session, "ghost@example.com")
    send.assert_not_called()


@pytest.mark.asyncio
async def test_request_reset_sends_link_to_verified_user(service, repo, session):
    user = _make_user()
    repo.find_by_email.return_value = user
    with patch(SEND) as send:
        await service.request_reset(session, user.user_email)
    to_email, url = send.call_args[0]
    assert to_email == user.user_email
    assert url.startswith(settings.PASSWORD_RESET_URL_BASE.rstrip("/") + "/reset-password?token=")


@pytest.mark.asyncio
async def test_consume_sets_password_bumps_version_and_unlocks(service, repo, throttle, session):
    user = _make_user(token_version=2)
    repo.find_by_id.return_value = user
    await service.consume_token(session, _token(user), "NewPassword123!")
    update_data = repo.update.call_args[0][2]
    assert update_data["user_password"].startswith("$2b$")
    assert update_data["token_version"] == 3
    throttle.clear.assert_awaited_once_with(session, user.user_email)


@pytest.mark.asyncio
async def test_consume_rejects_token_after_password_already_changed(service, repo, session):
    user = _make_user()
    repo.find_by_id.return_value = user
    with pytest.raises(ValidationError):
        await service.consume_token(session, _token(user, prefix="stale-prefix-000"), "NewPassword123!")
    repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_consume_rejects_unknown_user(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(ValidationError):
        await service.consume_token(session, _token(_make_user()), "NewPassword123!")


@pytest.mark.asyncio
async def test_consume_rejects_wrong_purpose(service, repo, session):
    user = _make_user()
    with pytest.raises(ValidationError):
        await service.consume_token(session, _token(user, purpose="email_verify"), "NewPassword123!")
    repo.find_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_consume_rejects_garbage(service, repo, session):
    with pytest.raises(ValidationError):
        await service.consume_token(session, "garbage", "NewPassword123!")
