"""Periodic housekeeping for auth tables.

Runs inside the API process (see main.lifespan). Can also be run by hand:

    python -m app.tasks.cleanup
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.repositories.login_attempt_repository import LoginAttemptRepository
from app.repositories.revoked_token_repository import RevokedTokenRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# Idle failed-login counters are dropped after this long.
LOGIN_ATTEMPT_RETENTION = timedelta(days=1)


@dataclass(frozen=True)
class CleanupReport:
    pending_users: int
    revoked_tokens: int
    login_attempts: int


class CleanupTask:
    def __init__(
        self,
        users: UserRepository | None = None,
        revoked: RevokedTokenRepository | None = None,
        attempts: LoginAttemptRepository | None = None,
    ):
        self._users = users or UserRepository()
        self._revoked = revoked or RevokedTokenRepository()
        self._attempts = attempts or LoginAttemptRepository()

    async def run(self, session: AsyncSession, *, now: datetime | None = None) -> CleanupReport:
        """Delete expired auth rows in one transaction and report the counts."""
        now = now or datetime.now(timezone.utc)
        pending = await self._users.delete_stale_pending(
            session, now - timedelta(hours=settings.PENDING_SIGNUP_TTL_HOURS)
        )
        revoked = await self._revoked.purge_expired(session, now)
        attempts = await self._attempts.purge_stale(
            session, before=now - LOGIN_ATTEMPT_RETENTION, now=now
        )
        await session.commit()
        return CleanupReport(pending, revoked, attempts)


async def run_forever(
    session_factory: async_sessionmaker,
    interval: timedelta,
    task: CleanupTask | None = None,
) -> None:
    """Run cleanup every `interval`, forever. Failures are logged, never fatal."""
    task = task or CleanupTask()
    while True:
        await asyncio.sleep(interval.total_seconds())
        try:
            async with session_factory() as session:
                report = await task.run(session)
            logger.info("auth cleanup: %s", report)
        except Exception:
            logger.exception("auth cleanup failed")


def start_background_cleanup() -> asyncio.Task:
    from app.database import async_session_factory

    return asyncio.create_task(
        run_forever(async_session_factory, timedelta(minutes=settings.CLEANUP_INTERVAL_MINUTES))
    )


async def _main() -> None:
    from app.database import async_session_factory, engine

    async with async_session_factory() as session:
        report = await CleanupTask().run(session)
    await engine.dispose()
    print(report)


if __name__ == "__main__":
    asyncio.run(_main())
