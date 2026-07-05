import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.user_repository import UserRepository

_user_repo = UserRepository()


async def is_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if the user's email is in the configured ADMIN_EMAILS allowlist.

    Admins may view all equipment and simulators regardless of ownership.
    Returns False fast (no DB query) when no admin emails are configured.
    """
    admins = settings.admin_emails
    if not admins:
        return False
    user = await _user_repo.find_by_id(session, user_id)
    return user is not None and user.user_email.lower() in admins
