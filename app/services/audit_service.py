import logging
import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.audit_log_repository import AuditLogRepository
from app.services.audit_context import Actor, get_actor, get_request_context

logger = logging.getLogger(__name__)

_MAX_UA = 512
_MAX_IP = 64


def jsonable(value):
    """Make audit details JSON-serialisable (uuid/datetime/enum/pydantic → plain)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (uuid.UUID, datetime, date)):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump())
    return value


class AuditService:
    """Writes append-only audit rows. Never raises: a broken audit sink must not
    turn into a platform outage, but every failure is logged loudly."""

    def __init__(self, repo: AuditLogRepository | None = None):
        self._repo = repo or AuditLogRepository()

    async def record(
        self,
        session: AsyncSession,
        action: str,
        *,
        resource_type: str | None = None,
        resource_id: object | None = None,
        target_user_id: uuid.UUID | None = None,
        details: dict | None = None,
        outcome: str = "success",
        actor: Actor | None = None,
    ) -> None:
        actor = actor or get_actor()
        ctx = get_request_context()
        data = {
            "actor_id": actor.user_id,
            "actor_email": actor.email,
            "actor_type": actor.actor_type,
            "action": action,
            "outcome": outcome,
            "resource_type": resource_type,
            "resource_id": None if resource_id is None else str(resource_id),
            "target_user_id": target_user_id,
            "ip_address": (ctx.ip_address or None) and ctx.ip_address[:_MAX_IP],
            "user_agent": (ctx.user_agent or None) and ctx.user_agent[:_MAX_UA],
            "request_id": ctx.request_id,
            "details": jsonable(details) if details else None,
        }
        try:
            await self._repo.add(session, data)
        except Exception:  # noqa: BLE001 - see class docstring
            logger.exception("audit record failed: action=%s actor=%s", action, actor.email)
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("audit rollback failed")


audit = AuditService()
