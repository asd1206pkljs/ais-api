from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.tasks.cleanup import LOGIN_ATTEMPT_RETENTION, CleanupReport, CleanupTask


@pytest.mark.asyncio
async def test_run_purges_all_three_tables_and_commits():
    users, revoked, attempts, session = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    users.delete_stale_pending.return_value = 3
    revoked.purge_expired.return_value = 5
    attempts.purge_stale.return_value = 2
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    report = await CleanupTask(users, revoked, attempts).run(session, now=now)

    assert report == CleanupReport(pending_users=3, revoked_tokens=5, login_attempts=2)
    users.delete_stale_pending.assert_awaited_once_with(
        session, now - timedelta(hours=settings.PENDING_SIGNUP_TTL_HOURS)
    )
    revoked.purge_expired.assert_awaited_once_with(session, now)
    attempts.purge_stale.assert_awaited_once_with(
        session, before=now - LOGIN_ATTEMPT_RETENTION, now=now
    )
    session.commit.assert_awaited_once()
