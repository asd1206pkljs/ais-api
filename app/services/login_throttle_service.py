from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import AccountLockedError
from app.repositories.login_attempt_repository import LoginAttemptRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LoginThrottleService:
    """Per-email lockout after repeated failed logins.

    Complements the per-IP rate limiter: an attacker rotating IPs against one
    account still gets only LOGIN_MAX_FAILURES guesses per lockout period.
    """

    def __init__(self, repo: LoginAttemptRepository):
        self._repo = repo

    async def check_not_locked(self, session: AsyncSession, email: str) -> None:
        """Raise AccountLockedError while a lock is in effect for `email`."""
        locked_until = await self._repo.get_locked_until(session, email)
        self._raise_if_locked(locked_until)

    async def record_failure(self, session: AsyncSession, email: str) -> None:
        """Count a failed attempt; raises AccountLockedError if it triggered a lock."""
        locked_until = await self._repo.record_failure(
            session,
            email,
            now=_now(),
            window=timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES),
            max_failures=settings.LOGIN_MAX_FAILURES,
            lockout=timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES),
        )
        self._raise_if_locked(locked_until)

    async def clear(self, session: AsyncSession, email: str) -> None:
        await self._repo.clear(session, email)

    @staticmethod
    def _raise_if_locked(locked_until: datetime | None) -> None:
        if locked_until is None:
            return
        remaining = (locked_until - _now()).total_seconds()
        if remaining > 0:
            raise AccountLockedError(int(remaining) + 1)
