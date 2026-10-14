from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.exceptions import AccountLockedError
from app.services.login_throttle_service import LoginThrottleService


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(repo):
    return LoginThrottleService(repo)


@pytest.fixture
def session():
    return AsyncMock()


def _in(seconds: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_check_passes_when_no_record(service, repo, session):
    repo.get_locked_until.return_value = None
    await service.check_not_locked(session, "a@example.com")


@pytest.mark.asyncio
async def test_check_passes_when_lock_expired(service, repo, session):
    repo.get_locked_until.return_value = _in(-1)
    await service.check_not_locked(session, "a@example.com")


@pytest.mark.asyncio
async def test_check_raises_with_remaining_seconds_while_locked(service, repo, session):
    repo.get_locked_until.return_value = _in(600)
    with pytest.raises(AccountLockedError) as exc:
        await service.check_not_locked(session, "a@example.com")
    assert 595 <= exc.value.retry_after_seconds <= 601
    assert "10 minute" in str(exc.value)


@pytest.mark.asyncio
async def test_record_failure_passes_settings_to_repo(service, repo, session):
    repo.record_failure.return_value = None
    await service.record_failure(session, "a@example.com")
    kwargs = repo.record_failure.call_args.kwargs
    assert kwargs["max_failures"] == settings.LOGIN_MAX_FAILURES
    assert kwargs["window"] == timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    assert kwargs["lockout"] == timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


@pytest.mark.asyncio
async def test_record_failure_raises_when_threshold_reached(service, repo, session):
    repo.record_failure.return_value = _in(900)
    with pytest.raises(AccountLockedError):
        await service.record_failure(session, "a@example.com")


@pytest.mark.asyncio
async def test_clear_delegates(service, repo, session):
    await service.clear(session, "a@example.com")
    repo.clear.assert_awaited_once_with(session, "a@example.com")
