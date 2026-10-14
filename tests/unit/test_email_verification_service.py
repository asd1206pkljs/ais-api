import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.exceptions import ConflictError, ValidationError
from app.models.user import User
from app.services import email_verification_service as evs
from app.services.email_verification_service import EmailVerificationService

SEND = "app.services.email_verification_service.send_verification_email"


def _make_user(**kwargs) -> User:
    defaults = {
        "user_id": uuid.uuid4(),
        "user_email": "test@example.com",
        "user_password": "hash",
        "approved": False,
    }
    defaults.update(kwargs)
    user = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _token(user_id, *, purpose=evs.PURPOSE, minutes=60) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(repo):
    return EmailVerificationService(repo)


@pytest.fixture
def session():
    return AsyncMock()


# --- send / resend -----------------------------------------------------------


def test_send_emails_link_with_token_for_user(service):
    user_id = uuid.uuid4()
    with patch(SEND) as send:
        service.send(user_id, "test@example.com")
    to_email, url = send.call_args[0]
    assert to_email == "test@example.com"
    assert url.startswith(settings.email_verify_url_base.rstrip("/") + "/verify-email?token=")
    token = url.split("token=", 1)[1]
    assert evs._decode_token(token) == user_id


@pytest.mark.asyncio
async def test_resend_targets_newest_pending_signup(service, repo, session):
    repo.find_by_email.return_value = None
    newest, older = _make_user(), _make_user()
    repo.find_pending_by_email.return_value = [newest, older]
    with patch(SEND) as send:
        await service.resend(session, "test@example.com")
    assert send.call_count == 1
    assert evs._decode_token(send.call_args[0][1].split("token=", 1)[1]) == newest.user_id


@pytest.mark.asyncio
async def test_resend_is_noop_when_email_already_verified(service, repo, session):
    repo.find_by_email.return_value = _make_user(approved=True)
    with patch(SEND) as send:
        await service.resend(session, "test@example.com")
    send.assert_not_called()
    repo.find_pending_by_email.assert_not_called()


@pytest.mark.asyncio
async def test_resend_is_noop_when_nothing_pending(service, repo, session):
    repo.find_by_email.return_value = None
    repo.find_pending_by_email.return_value = []
    with patch(SEND) as send:
        await service.resend(session, "unknown@example.com")
    send.assert_not_called()


# --- consume_token -----------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_approves_user_and_removes_other_pending(service, repo, session):
    user = _make_user()
    repo.find_by_id.return_value = user
    repo.find_by_email.return_value = None
    await service.consume_token(session, _token(user.user_id))
    repo.update.assert_awaited_once_with(session, user.user_id, {"approved": True})
    repo.delete_pending_by_email.assert_awaited_once_with(
        session, user.user_email, exclude_user_id=user.user_id
    )
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_consume_is_idempotent_for_already_approved_user(service, repo, session):
    user = _make_user(approved=True)
    repo.find_by_id.return_value = user
    await service.consume_token(session, _token(user.user_id))
    repo.update.assert_not_called()
    repo.delete_pending_by_email.assert_not_called()


@pytest.mark.asyncio
async def test_consume_discards_signup_when_email_verified_by_another_account(
    service, repo, session
):
    user = _make_user()
    repo.find_by_id.return_value = user
    repo.find_by_email.return_value = _make_user(approved=True)
    with pytest.raises(ConflictError):
        await service.consume_token(session, _token(user.user_id))
    repo.delete.assert_awaited_once_with(session, user.user_id)
    repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_consume_handles_lost_race_on_unique_index(service, repo, session):
    user = _make_user()
    repo.find_by_id.return_value = user
    repo.find_by_email.return_value = None
    repo.update.side_effect = IntegrityError("stmt", {}, Exception("dup"))
    with pytest.raises(ConflictError):
        await service.consume_token(session, _token(user.user_id))
    session.rollback.assert_awaited_once()
    repo.delete.assert_awaited_once_with(session, user.user_id)


@pytest.mark.asyncio
async def test_consume_rejects_unknown_user(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(ValidationError):
        await service.consume_token(session, _token(uuid.uuid4()))


@pytest.mark.asyncio
async def test_consume_rejects_garbage_token(service, repo, session):
    with pytest.raises(ValidationError):
        await service.consume_token(session, "not-a-jwt")
    repo.find_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_consume_rejects_expired_token(service, repo, session):
    with pytest.raises(ValidationError):
        await service.consume_token(session, _token(uuid.uuid4(), minutes=-5))


@pytest.mark.asyncio
async def test_consume_rejects_token_issued_for_other_purpose(service, repo, session):
    # A password-reset token must not be usable to verify an email.
    with pytest.raises(ValidationError):
        await service.consume_token(session, _token(uuid.uuid4(), purpose="pwd_reset"))
    repo.find_by_id.assert_not_called()
