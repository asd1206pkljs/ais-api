from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.revoked_token_repository import RevokedTokenRepository


class TokenRevocationService:
    """Denylist for individual access tokens (logout before expiry)."""

    def __init__(self, repo: RevokedTokenRepository):
        self._repo = repo

    async def revoke(self, session: AsyncSession, payload: dict) -> None:
        """Revoke the token described by a decoded JWT payload."""
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        await self._repo.add(session, payload["jti"], expires_at)

    async def is_revoked(self, session: AsyncSession, jti: str) -> bool:
        return await self._repo.exists(session, jti)
