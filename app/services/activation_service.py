"""What happens to an account once its e-mail is verified.

Policy: SIGNUP_REQUIRE_APPROVAL off, or the e-mail domain is allow-listed, →
the account goes straight to `active`. Otherwise it waits in
`pending_approval` with a sign-up request queued for administrators.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import RequestStatus, UserStatus
from app.enums import audit_action as act
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services import notifications
from app.services.audit_service import AuditService, audit
from app.services.request_service import RequestService


def auto_approves(email: str) -> bool:
    if not settings.SIGNUP_REQUIRE_APPROVAL:
        return True
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return domain in settings.signup_auto_approve_domains


class ActivationService:
    def __init__(
        self,
        user_repo: UserRepository | None = None,
        requests: RequestService | None = None,
        audit_svc: AuditService = audit,
    ):
        self._users = user_repo or UserRepository()
        self._requests = requests or RequestService(user_repo=self._users, audit_svc=audit_svc)
        self._audit = audit_svc

    async def on_email_verified(self, session: AsyncSession, user: User) -> str:
        """Set the post-verification status and return it."""
        if user.status == UserStatus.ACTIVE.value:
            return user.status
        if auto_approves(user.user_email):
            await self._users.update(session, user.user_id, {"status": UserStatus.ACTIVE.value})
            await self._requests.resolve_pending_signup(
                session, user.user_id, None, RequestStatus.AUTO_APPROVED, "Activated by policy"
            )
            await session.commit()
            await self._audit.record(session, act.ACCOUNT_ACTIVATED, target_user_id=user.user_id,
                                     details={"by": "policy"})
            notifications.notify_user_account_activated(user.user_email)
            return UserStatus.ACTIVE.value
        await self._users.update(session, user.user_id, {"status": UserStatus.PENDING_APPROVAL.value})
        await self._requests.ensure_signup_request(session, user)
        notifications.notify_user_account_pending(user.user_email)
        return UserStatus.PENDING_APPROVAL.value
