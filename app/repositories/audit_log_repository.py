from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


@dataclass(frozen=True)
class AuditQuery:
    actor_id: object | None = None
    target_user_id: object | None = None
    action: str | None = None
    action_prefix: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class AuditLogRepository:
    async def add(self, session: AsyncSession, data: dict) -> AuditLog:
        row = AuditLog(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    @staticmethod
    def _conditions(q: AuditQuery) -> list:
        conditions = []
        if q.actor_id is not None:
            conditions.append(AuditLog.actor_id == q.actor_id)
        if q.target_user_id is not None:
            conditions.append(AuditLog.target_user_id == q.target_user_id)
        if q.action:
            conditions.append(AuditLog.action == q.action)
        if q.action_prefix:
            conditions.append(AuditLog.action.startswith(q.action_prefix, autoescape=True))
        if q.resource_type:
            conditions.append(AuditLog.resource_type == q.resource_type)
        if q.resource_id:
            conditions.append(AuditLog.resource_id == q.resource_id)
        if q.outcome:
            conditions.append(AuditLog.outcome == q.outcome)
        if q.since is not None:
            conditions.append(AuditLog.occurred_at >= q.since)
        if q.until is not None:
            conditions.append(AuditLog.occurred_at <= q.until)
        return conditions

    async def search(
        self, session: AsyncSession, q: AuditQuery, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        result = await session.execute(
            select(AuditLog)
            .where(*self._conditions(q))
            .order_by(AuditLog.occurred_at.desc(), AuditLog.log_id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count(self, session: AsyncSession, q: AuditQuery) -> int:
        result = await session.execute(
            select(func.count()).select_from(AuditLog).where(*self._conditions(q))
        )
        return result.scalar_one()
