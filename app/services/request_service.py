"""User requests (sign-up approval, credits): submission, policy-based auto
approval, admin decisions, and the side effects of a decision."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import RequestStatus, RequestType, UserStatus
from app.enums import audit_action as act
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.user_request import UserRequest
from app.repositories.user_repository import UserRepository
from app.repositories.user_request_repository import UserRequestRepository
from app.schemas.common import PaginationMeta
from app.schemas.request import RequestAdminRead, RequestDecision, RequestRead
from app.services import notifications
from app.services.audit_service import AuditService, audit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _meta(total: int, skip: int, limit: int) -> PaginationMeta:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return PaginationMeta(total=total, page=(skip // limit) + 1 if limit else 1, limit=limit, pages=pages)


def _read(req: UserRequest) -> RequestRead:
    return RequestRead(
        request_id=req.request_id, user_id=req.user_id, request_type=req.request_type,
        status=req.status, payload=req.payload or {}, decision_note=req.decision_note,
        decided_at=req.decided_at, created_at=req.created_at,
    )


def _admin_read(req: UserRequest, email: str, name: str) -> RequestAdminRead:
    return RequestAdminRead(**_read(req).model_dump(), user_email=email, user_name=name,
                            decided_by=req.decided_by)


class RequestService:
    def __init__(
        self,
        repo: UserRequestRepository | None = None,
        user_repo: UserRepository | None = None,
        audit_svc: AuditService = audit,
    ):
        self._repo = repo or UserRequestRepository()
        self._users = user_repo or UserRepository()
        self._audit = audit_svc

    # --- submission -----------------------------------------------------------

    async def _auto_approves_credit(self, session: AsyncSession, user_id: uuid.UUID, amount: int) -> bool:
        cap = settings.CREDIT_REQUEST_AUTO_APPROVE_MAX
        if cap <= 0 or amount > cap:
            return False
        since = _now() - timedelta(days=settings.CREDIT_REQUEST_AUTO_APPROVE_WINDOW_DAYS)
        return not await self._repo.has_auto_approved_since(session, user_id, RequestType.CREDIT.value, since)

    async def submit_credit_request(
        self, session: AsyncSession, user_id: uuid.UUID, requested_amount: int, reason: str | None
    ) -> RequestRead:
        user = await self._users.find_by_id(session, user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        if await self._repo.find_pending(session, user_id, RequestType.CREDIT.value) is not None:
            raise ConflictError("You already have a pending credit request")
        payload = {"requested_amount": requested_amount, "reason": reason}
        auto = await self._auto_approves_credit(session, user_id, requested_amount)
        try:
            req = await self._repo.create(session, {
                "user_id": user_id,
                "request_type": RequestType.CREDIT.value,
                "status": RequestStatus.PENDING.value,
                "payload": payload,
            })
        except IntegrityError:  # lost a race with a concurrent submission
            await session.rollback()
            raise ConflictError("You already have a pending credit request")
        await self._audit.record(session, act.REQUEST_SUBMITTED, resource_type="request",
                                 resource_id=req.request_id, details=payload)
        if auto:
            req = await self._decide(session, req, RequestStatus.AUTO_APPROVED, decided_by=None,
                                     note="Granted automatically by policy", granted_amount=requested_amount)
            await self._audit.record(session, act.REQUEST_AUTO_APPROVED, resource_type="request",
                                     resource_id=req.request_id, details={"granted_amount": requested_amount})
            notifications.notify_user_request_decided(user.user_email, req)
        else:
            notifications.notify_admins_new_request(req, user.user_email, user.user_name)
            notifications.notify_user_request_received(user.user_email, req)
        return _read(req)

    async def ensure_signup_request(self, session: AsyncSession, user) -> UserRequest:
        """Queue a sign-up approval for `user` (idempotent while one is pending)."""
        existing = await self._repo.find_pending(session, user.user_id, RequestType.SIGNUP_APPROVAL.value)
        if existing is not None:
            return existing
        req = await self._repo.create(session, {
            "user_id": user.user_id,
            "request_type": RequestType.SIGNUP_APPROVAL.value,
            "status": RequestStatus.PENDING.value,
            "payload": {"email": user.user_email, "company": user.user_company},
        })
        await self._audit.record(session, act.REQUEST_SUBMITTED, resource_type="request",
                                 resource_id=req.request_id, target_user_id=user.user_id,
                                 details={"request_type": req.request_type})
        notifications.notify_admins_new_request(req, user.user_email, user.user_name)
        return req

    async def resolve_pending_signup(self, session: AsyncSession, user_id: uuid.UUID, admin_id: uuid.UUID | None,
                                     status: RequestStatus, note: str | None) -> None:
        """Close a pending sign-up request when an admin changes the account status directly."""
        pending = await self._repo.find_pending(session, user_id, RequestType.SIGNUP_APPROVAL.value)
        if pending is not None:
            await self._repo.update(session, pending.request_id, {
                "status": status.value, "decided_by": admin_id, "decided_at": _now(), "decision_note": note,
            })

    # --- listing ----------------------------------------------------------------

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, status: str | None, skip: int, limit: int
    ) -> tuple[list[RequestRead], PaginationMeta]:
        rows = await self._repo.list_with_user(session, user_id=user_id, status=status, skip=skip, limit=limit)
        total = await self._repo.count(session, user_id=user_id, status=status)
        return [_read(r) for r, _, _ in rows], _meta(total, skip, limit)

    async def list_all(
        self, session: AsyncSession, status: str | None, request_type: str | None, skip: int, limit: int
    ) -> tuple[list[RequestAdminRead], PaginationMeta]:
        rows = await self._repo.list_with_user(session, status=status, request_type=request_type,
                                               skip=skip, limit=limit)
        total = await self._repo.count(session, status=status, request_type=request_type)
        return [_admin_read(r, e, n) for r, e, n in rows], _meta(total, skip, limit)

    # --- decisions --------------------------------------------------------------

    async def _load_pending(self, session: AsyncSession, request_id: uuid.UUID) -> UserRequest:
        req = await self._repo.find_by_id(session, request_id)
        if req is None:
            raise NotFoundError("Request", str(request_id))
        if req.status != RequestStatus.PENDING.value:
            raise ConflictError(f"Request already {req.status}")
        return req

    async def _decide(
        self, session: AsyncSession, req: UserRequest, status: RequestStatus, *,
        decided_by: uuid.UUID | None, note: str | None, granted_amount: int | None = None,
    ) -> UserRequest:
        """Record the decision and apply its effect in one transaction."""
        payload = dict(req.payload or {})
        approved = status in (RequestStatus.APPROVED, RequestStatus.AUTO_APPROVED)
        if approved:
            await self._apply(session, req, payload, granted_amount)
        # Conditional on still being pending: a concurrent decision loses and
        # its side effects are rolled back with the transaction.
        updated = await self._repo.transition(session, req.request_id, RequestStatus.PENDING.value, {
            "status": status.value, "decided_by": decided_by, "decided_at": _now(),
            "decision_note": note, "payload": payload,
        })
        if updated is None:
            await session.rollback()
            raise ConflictError("Request was already decided")
        await session.commit()
        await session.refresh(updated)
        return updated

    async def _apply(self, session: AsyncSession, req: UserRequest, payload: dict, granted_amount: int | None) -> None:
        if req.request_type == RequestType.CREDIT.value:
            amount = granted_amount or int(payload.get("requested_amount") or 0)
            if amount <= 0:
                raise ValidationError("Nothing to grant")
            payload["granted_amount"] = amount
            await self._users.refund_credit(session, req.user_id, amount)
        elif req.request_type == RequestType.SIGNUP_APPROVAL.value:
            user = await self._users.find_by_id(session, req.user_id)
            if user is None:
                raise NotFoundError("User", str(req.user_id))
            user.status = UserStatus.ACTIVE.value
            await session.flush()

    async def approve(
        self, session: AsyncSession, admin_id: uuid.UUID, request_id: uuid.UUID, data: RequestDecision
    ) -> RequestAdminRead:
        req = await self._load_pending(session, request_id)
        req = await self._decide(session, req, RequestStatus.APPROVED, decided_by=admin_id,
                                 note=data.note, granted_amount=data.granted_amount)
        user = await self._users.find_by_id(session, req.user_id)
        await self._audit.record(session, act.REQUEST_APPROVED, resource_type="request",
                                 resource_id=req.request_id, target_user_id=req.user_id,
                                 details={"request_type": req.request_type, "payload": req.payload})
        if user is not None:
            notifications.notify_user_request_decided(user.user_email, req)
            if req.request_type == RequestType.SIGNUP_APPROVAL.value:
                await self._audit.record(session, act.ACCOUNT_ACTIVATED, target_user_id=user.user_id)
                notifications.notify_user_account_activated(user.user_email)
        return _admin_read(req, user.user_email if user else "", user.user_name if user else "")

    async def reject(
        self, session: AsyncSession, admin_id: uuid.UUID, request_id: uuid.UUID, data: RequestDecision
    ) -> RequestAdminRead:
        req = await self._load_pending(session, request_id)
        req = await self._decide(session, req, RequestStatus.REJECTED, decided_by=admin_id, note=data.note)
        user = await self._users.find_by_id(session, req.user_id)
        await self._audit.record(session, act.REQUEST_REJECTED, resource_type="request",
                                 resource_id=req.request_id, target_user_id=req.user_id,
                                 details={"request_type": req.request_type, "note": data.note})
        if user is not None:
            notifications.notify_user_request_decided(user.user_email, req)
        return _admin_read(req, user.user_email if user else "", user.user_name if user else "")
