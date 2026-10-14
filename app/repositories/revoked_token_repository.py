from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.revoked_token import RevokedToken


class RevokedTokenRepository:
    async def add(self, session: AsyncSession, jti: str, expires_at: datetime) -> None:
        """Denylist a token id; revoking twice is a no-op. Commits."""
        stmt = (
            pg_insert(RevokedToken)
            .values(jti=jti, expires_at=expires_at)
            .on_conflict_do_nothing(index_elements=[RevokedToken.jti])
        )
        await session.execute(stmt)
        await session.commit()

    async def exists(self, session: AsyncSession, jti: str) -> bool:
        result = await session.execute(select(RevokedToken.jti).where(RevokedToken.jti == jti))
        return result.scalar_one_or_none() is not None

    async def purge_expired(self, session: AsyncSession, before: datetime) -> int:
        """Drop denylist rows whose token has expired anyway. Caller commits."""
        result = await session.execute(delete(RevokedToken).where(RevokedToken.expires_at < before))
        return result.rowcount
