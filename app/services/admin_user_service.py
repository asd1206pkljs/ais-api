"""Admin console operations on accounts: list, role/status changes, credits.

Only metadata is ever returned; nothing here reads resource content.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import RequestStatus, UserRole, UserStatus
from app.enums import audit_action as act
from app.exceptions import NotFoundError, ValidationError
from app.models.user import User
from app.repositories.group_repository import GroupRepository
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminUserRead, AdminUserUpdate, CreditAdjustment
from app.schemas.common import PaginationMeta
from app.schemas.group import GroupMembership
from app.services import notifications
from app.services.audit_service import AuditService, audit
from app.services.request_service import RequestService


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


class AdminUserService:
    def __init__(
        self,
        user_repo: UserRepository | None = None,
        group_repo: GroupRepository | None = None,
        requests: RequestService | None = None,
        audit_svc: AuditService = audit,
    ):
        self._users = user_repo or UserRepository()
        self._groups = group_repo or GroupRepository()
        self._requests = requests or RequestService(user_repo=self._users, audit_svc=audit_svc)
        self._audit = audit_svc

    async def _read(self, session: AsyncSession, user: User) -> AdminUserRead:
        groups = [
            GroupMembership(group_id=g.group_id, group_name=g.group_name, role=m.role)
            for g, m in await self._groups.find_for_user(session, user.user_id)
        ]
        return AdminUserRead(
            user_id=user.user_id, user_name=user.user_name, user_email=user.user_email,
            user_company=user.user_company, user_credits=user.user_credits, role=user.role,
            status=user.status, approved=user.approved, joined_at=user.joined_at,
            last_login_at=user.last_login_at, groups=groups,
        )

    async def _load(self, session: AsyncSession, user_id: uuid.UUID) -> User:
        user = await self._users.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return user

    async def list_users(
        self, session: AsyncSession, *, status: str | None, role: str | None, q: str | None, skip: int, limit: int
    ) -> tuple[list[AdminUserRead], PaginationMeta]:
        users = await self._users.search(session, status=status, role=role, q=q, skip=skip, limit=limit)
        total = await self._users.count_search(session, status=status, role=role, q=q)
        return [await self._read(session, u) for u in users], _meta(total, skip, limit)

    async def get_user(self, session: AsyncSession, user_id: uuid.UUID) -> AdminUserRead:
        return await self._read(session, await self._load(session, user_id))

    async def update_user(
        self, session: AsyncSession, admin_id: uuid.UUID, user_id: uuid.UUID, data: AdminUserUpdate
    ) -> AdminUserRead:
        user = await self._load(session, user_id)
        if user_id == admin_id and (data.role == UserRole.USER or data.status == UserStatus.DISABLED):
            raise ValidationError("You cannot demote or disable your own account")
        changes: dict = {}
        if data.role is not None and data.role.value != user.role:
            changes["role"] = data.role.value
        if data.status is not None and data.status.value != user.status:
            changes["status"] = data.status.value
            if data.status == UserStatus.DISABLED:
                changes["token_version"] = user.token_version + 1  # end every session now
        if not changes:
            return await self._read(session, user)
        updated = await self._users.update(session, user_id, changes)
        if "status" in changes:
            decision = RequestStatus.APPROVED if data.status == UserStatus.ACTIVE else RequestStatus.REJECTED
            await self._requests.resolve_pending_signup(session, user_id, admin_id, decision, data.note)
            await session.commit()
            action = act.ACCOUNT_ACTIVATED if data.status == UserStatus.ACTIVE else act.ACCOUNT_DISABLED
            await self._audit.record(session, action, target_user_id=user_id,
                                     details={"status": data.status.value, "note": data.note})
            if data.status == UserStatus.ACTIVE:
                notifications.notify_user_account_activated(updated.user_email)
            elif data.status == UserStatus.DISABLED:
                notifications.notify_user_account_disabled(updated.user_email)
        if "role" in changes:
            await self._audit.record(session, act.ACCOUNT_ROLE_CHANGED, target_user_id=user_id,
                                     details={"role": changes["role"], "note": data.note})
        return await self._read(session, updated)

    async def adjust_credits(
        self, session: AsyncSession, admin_id: uuid.UUID, user_id: uuid.UUID, data: CreditAdjustment
    ) -> AdminUserRead:
        user = await self._load(session, user_id)
        if data.amount < 0 and user.user_credits + data.amount < 0:
            raise ValidationError("Balance cannot go negative")
        await self._users.refund_credit(session, user_id, data.amount)
        await session.commit()
        await self._audit.record(session, act.CREDITS_ADJUSTED, target_user_id=user_id,
                                 details={"amount": data.amount, "reason": data.reason, "by": str(admin_id)})
        return await self._read(session, await self._load(session, user_id))
