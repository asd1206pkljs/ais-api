import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import (
    AccountLockedError,
    AuthenticationError,
    ConflictError,
    EmailNotVerifiedError,
    NotFoundError,
)
from app.models.user import User
from app.schemas.consent import ConsentInput
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import hash_password
from app.services.user_service import UserService

CONSENTS = ConsentInput(terms_version="2026-10-01", privacy_version="2026-10-01")


def _make_user(**kwargs) -> User:
    defaults = {
        "user_id": uuid.uuid4(),
        "user_name": "Test User",
        "user_email": "test@example.com",
        "user_password": hash_password("password123"),
        "user_company": None,
        "user_credits": 0,
        "approved": True,
        "token_version": 0,
        "role": "user",
        "status": "active",
        "joined_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    defaults.update(kwargs)
    user = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def throttle():
    return AsyncMock()


@pytest.fixture
def service(repo, throttle):
    return UserService(repo, throttle)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_register_success_creates_unverified_account(service, repo, session):
    repo.find_by_email.return_value = None
    repo.create.return_value = _make_user(approved=False, user_company="ACME")
    result = await service.register(session, UserCreate(
        user_name="Test", user_email="test@example.com", user_password="Password123!",
        user_company="ACME",
    ), consents=CONSENTS)
    assert result.user_email == "test@example.com"
    assert result.approved is False
    created = repo.create.call_args[0][1]
    assert created["approved"] is False
    assert created["user_company"] == "ACME"


@pytest.mark.asyncio
async def test_register_blocked_by_approved_duplicate(service, repo, session):
    repo.find_by_email.return_value = _make_user(approved=True)
    with pytest.raises(ConflictError):
        await service.register(session, UserCreate(
            user_name="Test", user_email="test@example.com", user_password="Password123!"
        ), consents=CONSENTS)
    repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_register_allowed_when_only_pending_duplicates_exist(service, repo, session):
    # find_by_email only returns approved accounts, so a pending sign-up
    # with the same email does not block registration.
    repo.find_by_email.return_value = None
    repo.create.return_value = _make_user(approved=False)
    result = await service.register(session, UserCreate(
        user_name="Test", user_email="test@example.com", user_password="Password123!"
    ), consents=CONSENTS)
    assert result.approved is False
    repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_success(service, repo, session):
    user = _make_user()
    repo.find_by_email.return_value = user
    repo.update.return_value = user
    repo.find_by_id.return_value = user
    result = await service.authenticate(session, "test@example.com", "password123")
    assert result.user_email == "test@example.com"


@pytest.mark.asyncio
async def test_authenticate_wrong_password(service, repo, session):
    repo.find_by_email.return_value = _make_user()
    repo.find_pending_by_email.return_value = []
    with pytest.raises(AuthenticationError):
        await service.authenticate(session, "test@example.com", "wrongpassword")


@pytest.mark.asyncio
async def test_authenticate_user_not_found(service, repo, session):
    repo.find_by_email.return_value = None
    repo.find_pending_by_email.return_value = []
    with pytest.raises(AuthenticationError):
        await service.authenticate(session, "nobody@example.com", "password123")


@pytest.mark.asyncio
async def test_authenticate_pending_account_with_correct_password_is_not_verified(
    service, repo, session
):
    repo.find_by_email.return_value = None
    repo.find_pending_by_email.return_value = [_make_user(approved=False)]
    with pytest.raises(EmailNotVerifiedError):
        await service.authenticate(session, "test@example.com", "password123")
    repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_pending_account_with_wrong_password_stays_generic(
    service, repo, session
):
    # Must not reveal that a pending sign-up exists.
    repo.find_by_email.return_value = None
    repo.find_pending_by_email.return_value = [_make_user(approved=False)]
    with pytest.raises(AuthenticationError):
        await service.authenticate(session, "test@example.com", "wrongpassword")


@pytest.mark.asyncio
async def test_get_by_id_not_found(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_by_id(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_update_hashes_password(service, repo, session):
    user = _make_user()
    repo.update.return_value = user
    await service.update(session, user.user_id, UserUpdate(user_password="NewPassword123!"))
    call_kwargs = repo.update.call_args[0][2]
    assert call_kwargs["user_password"] != "NewPassword123!"
    assert call_kwargs["user_password"].startswith("$2b$")


# --- lockout / timing --------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_locked_account_is_refused_before_password_check(
    service, repo, throttle, session
):
    throttle.check_not_locked.side_effect = AccountLockedError(600)
    with pytest.raises(AccountLockedError):
        await service.authenticate(session, "test@example.com", "password123")
    repo.find_by_email.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_success_clears_failure_counter(service, repo, throttle, session):
    user = _make_user()
    repo.find_by_email.return_value = user
    repo.update.return_value = user
    repo.find_by_id.return_value = user
    await service.authenticate(session, "test@example.com", "password123")
    throttle.clear.assert_awaited_once_with(session, "test@example.com")
    throttle.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_failure_is_counted(service, repo, throttle, session):
    repo.find_by_email.return_value = _make_user()
    repo.find_pending_by_email.return_value = []
    with pytest.raises(AuthenticationError):
        await service.authenticate(session, "test@example.com", "wrongpassword")
    throttle.record_failure.assert_awaited_once_with(session, "test@example.com")
    throttle.clear.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_failure_that_trips_lockout_reports_lock(
    service, repo, throttle, session
):
    repo.find_by_email.return_value = _make_user()
    throttle.record_failure.side_effect = AccountLockedError(900)
    with pytest.raises(AccountLockedError):
        await service.authenticate(session, "test@example.com", "wrongpassword")


@pytest.mark.asyncio
async def test_authenticate_unknown_email_still_runs_bcrypt(service, repo, session):
    # Same bcrypt cost as a wrong password, so timing does not reveal existence.
    from app.services.auth_service import DUMMY_PASSWORD_HASH

    repo.find_by_email.return_value = None
    repo.find_pending_by_email.return_value = []
    with patch("app.services.user_service.verify_password", return_value=False) as verify:
        with pytest.raises(AuthenticationError):
            await service.authenticate(session, "nobody@example.com", "password123")
    verify.assert_any_call("password123", DUMMY_PASSWORD_HASH)


# --- token versioning --------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_bumps_token_version(service, repo, session):
    user = _make_user(token_version=4)
    repo.find_by_id.return_value = user
    repo.update.return_value = user
    await service.change_password(session, user.user_id, "password123", "NewPassword123!")
    update_data = repo.update.call_args[0][2]
    assert update_data["token_version"] == 5
    assert update_data["user_password"].startswith("$2b$")


@pytest.mark.asyncio
async def test_update_with_password_bumps_token_version(service, repo, session):
    user = _make_user(token_version=1)
    repo.find_by_id.return_value = user
    repo.update.return_value = user
    await service.update(session, user.user_id, UserUpdate(user_password="NewPassword123!"))
    assert repo.update.call_args[0][2]["token_version"] == 2


@pytest.mark.asyncio
async def test_update_without_password_leaves_token_version_alone(service, repo, session):
    user = _make_user()
    repo.update.return_value = user
    await service.update(session, user.user_id, UserUpdate(user_name="New Name"))
    assert "token_version" not in repo.update.call_args[0][2]


@pytest.mark.asyncio
async def test_issue_access_token_carries_current_version(service, repo, session):
    from app.services.auth_service import decode_access_token

    user = _make_user(token_version=7)
    repo.find_by_id.return_value = user
    token = await service.issue_access_token(session, user.user_id)
    assert decode_access_token(token)["ver"] == 7
