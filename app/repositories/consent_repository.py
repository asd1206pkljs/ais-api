import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent_record import ConsentRecord


class ConsentRepository:
    async def add_many(self, session: AsyncSession, records: list[dict]) -> list[ConsentRecord]:
        """Append consent rows. Caller commits."""
        rows = [ConsentRecord(**r) for r in records]
        session.add_all(rows)
        await session.flush()
        return rows

    async def list_for_user(self, session: AsyncSession, user_id: uuid.UUID) -> list[ConsentRecord]:
        result = await session.execute(
            select(ConsentRecord)
            .where(ConsentRecord.user_id == user_id)
            .order_by(ConsentRecord.accepted_at.desc())
        )
        return list(result.scalars().all())

    async def latest_for_user(self, session: AsyncSession, user_id: uuid.UUID) -> dict[str, ConsentRecord]:
        """Most recent record per document name."""
        latest: dict[str, ConsentRecord] = {}
        for record in await self.list_for_user(session, user_id):
            latest.setdefault(record.document, record)
        return latest
