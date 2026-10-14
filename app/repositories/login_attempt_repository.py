from datetime import datetime, timedelta

from sqlalchemy import case, delete, null, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.login_attempt import LoginAttempt


class LoginAttemptRepository:
    async def get_locked_until(self, session: AsyncSession, email: str) -> datetime | None:
        result = await session.execute(
            select(LoginAttempt.locked_until).where(LoginAttempt.email == email)
        )
        return result.scalar_one_or_none()

    async def record_failure(
        self,
        session: AsyncSession,
        email: str,
        *,
        now: datetime,
        window: timedelta,
        max_failures: int,
        lockout: timedelta,
    ) -> datetime | None:
        """Count one failed attempt atomically and return the resulting lock expiry.

        Failures older than `window` restart the count. Once the count reaches
        `max_failures` the row is locked for `lockout`. Done in a single upsert so
        concurrent attempts cannot race past the threshold. Commits.
        """
        new_count = case(
            (LoginAttempt.last_failed_at < now - window, 1),
            else_=LoginAttempt.failed_count + 1,
        )
        stmt = (
            pg_insert(LoginAttempt)
            .values(email=email, failed_count=1, last_failed_at=now, locked_until=None)
            .on_conflict_do_update(
                index_elements=[LoginAttempt.email],
                set_={
                    "failed_count": new_count,
                    "last_failed_at": now,
                    "locked_until": case((new_count >= max_failures, now + lockout), else_=null()),
                },
            )
            .returning(LoginAttempt.locked_until)
        )
        locked_until = (await session.execute(stmt)).scalar_one()
        await session.commit()
        return locked_until

    async def clear(self, session: AsyncSession, email: str) -> None:
        """Forget failures for `email` (successful login / password reset). Commits."""
        await session.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
        await session.commit()

    async def purge_stale(self, session: AsyncSession, *, before: datetime, now: datetime) -> int:
        """Delete counters idle since `before` that are not currently locked. Caller commits."""
        result = await session.execute(
            delete(LoginAttempt).where(
                LoginAttempt.last_failed_at < before,
                or_(LoginAttempt.locked_until.is_(None), LoginAttempt.locked_until < now),
            )
        )
        return result.rowcount
