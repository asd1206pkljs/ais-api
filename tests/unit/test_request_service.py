import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enums import RequestStatus, RequestType
from app.exceptions import ConflictError, NotFoundError
from app.schemas.request import RequestDecision
from app.services.request_service import RequestService


def _user(uid=None, status="pending_approval"):
    u = MagicMock()
    u.user_id = uid or uuid.uuid4()
    u.user_email = "u@example.com"
    u.user_name = "U"
    u.user_company = None
    u.status = status
    return u


def _request(rtype=RequestType.CREDIT.value, status="pending", payload=None, uid=None):
    r = MagicMock()
    r.request_id = uuid.uuid4()
    r.user_id = uid or uuid.uuid4()
    r.request_type = rtype
    r.status = status
    r.payload = payload or {}
    r.decision_note = None
    r.decided_at = None
    r.decided_by = None
    r.created_at = MagicMock()
    return r


@pytest.fixture
def repo():
    r = AsyncMock()
    r.find_pending.return_value = None
    r.has_auto_approved_since.return_value = False

    async def update(session, request_id, data):
        row = r.find_by_id.return_value
        for k, v in data.items():
            setattr(row, k, v)
        return row

    async def transition(session, request_id, from_status, data):
        row = r.find_by_id.return_value
        if row.status != from_status:
            return None
        return await update(session, request_id, data)

    r.update.side_effect = update
    r.transition.side_effect = transition
    return r


@pytest.fixture
def users():
    return AsyncMock()


@pytest.fixture
def service(repo, users):
    return RequestService(repo, users, AsyncMock())


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture(autouse=True)
def quiet_notifications():
    with patch("app.services.request_service.notifications") as n:
        yield n


@pytest.mark.asyncio
async def test_credit_request_pending_by_default(service, repo, users, session, quiet_notifications):
    user = _user(status="active")
    users.find_by_id.return_value = user
    created = _request(payload={"requested_amount": 5, "reason": "demo"}, uid=user.user_id)
    repo.create.return_value = created
    read = await service.submit_credit_request(session, user.user_id, 5, "demo")
    assert read.status == RequestStatus.PENDING and read.payload["requested_amount"] == 5
    quiet_notifications.notify_admins_new_request.assert_called_once()
    quiet_notifications.notify_user_request_received.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_pending_credit_request_rejected(service, repo, users, session):
    users.find_by_id.return_value = _user()
    repo.find_pending.return_value = _request()
    with pytest.raises(ConflictError):
        await service.submit_credit_request(session, uuid.uuid4(), 1, None)
    users.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.submit_credit_request(session, uuid.uuid4(), 1, None)


@pytest.mark.asyncio
async def test_auto_approval_policy(service, repo, users, session, quiet_notifications):
    user = _user(status="active")
    users.find_by_id.return_value = user
    created = _request(payload={"requested_amount": 2, "reason": None}, uid=user.user_id)
    repo.create.return_value = created
    repo.find_by_id.return_value = created
    with patch("app.services.request_service.settings") as settings:
        settings.CREDIT_REQUEST_AUTO_APPROVE_MAX = 3
        settings.CREDIT_REQUEST_AUTO_APPROVE_WINDOW_DAYS = 30
        read = await service.submit_credit_request(session, user.user_id, 2, None)
    assert read.status == RequestStatus.AUTO_APPROVED
    users.refund_credit.assert_awaited_once_with(session, user.user_id, 2)
    assert created.payload["granted_amount"] == 2
    quiet_notifications.notify_user_request_decided.assert_called_once()
    quiet_notifications.notify_admins_new_request.assert_not_called()

    # Over the cap, or already auto-approved recently → pending.
    users.refund_credit.reset_mock()
    repo.create.return_value = _request(payload={"requested_amount": 2}, uid=user.user_id)
    repo.has_auto_approved_since.return_value = True
    with patch("app.services.request_service.settings") as settings:
        settings.CREDIT_REQUEST_AUTO_APPROVE_MAX = 3
        settings.CREDIT_REQUEST_AUTO_APPROVE_WINDOW_DAYS = 30
        assert (await service.submit_credit_request(session, user.user_id, 2, None)).status == RequestStatus.PENDING
    users.refund_credit.assert_not_called()


@pytest.mark.asyncio
async def test_approve_credit_grants_amount(service, repo, users, session, quiet_notifications):
    admin = uuid.uuid4()
    req = _request(payload={"requested_amount": 10})
    repo.find_by_id.return_value = req
    users.find_by_id.return_value = _user(req.user_id, status="active")
    read = await service.approve(session, admin, req.request_id, RequestDecision(note="ok", granted_amount=4))
    users.refund_credit.assert_awaited_once_with(session, req.user_id, 4)
    assert read.status == RequestStatus.APPROVED and read.payload["granted_amount"] == 4
    assert read.decided_by == admin and read.user_email == "u@example.com"
    session.commit.assert_awaited()
    quiet_notifications.notify_user_request_decided.assert_called_once()


@pytest.mark.asyncio
async def test_approve_signup_activates_account(service, repo, users, session, quiet_notifications):
    req = _request(rtype=RequestType.SIGNUP_APPROVAL.value)
    user = _user(req.user_id)
    repo.find_by_id.return_value = req
    users.find_by_id.return_value = user
    await service.approve(session, uuid.uuid4(), req.request_id, RequestDecision())
    assert user.status == "active"
    quiet_notifications.notify_user_account_activated.assert_called_once_with("u@example.com")


@pytest.mark.asyncio
async def test_reject_and_already_decided(service, repo, users, session, quiet_notifications):
    req = _request()
    repo.find_by_id.return_value = req
    users.find_by_id.return_value = _user(req.user_id)
    read = await service.reject(session, uuid.uuid4(), req.request_id, RequestDecision(note="no"))
    assert read.status == RequestStatus.REJECTED and read.decision_note == "no"
    users.refund_credit.assert_not_called()
    with pytest.raises(ConflictError):
        await service.reject(session, uuid.uuid4(), req.request_id, RequestDecision())
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.approve(session, uuid.uuid4(), uuid.uuid4(), RequestDecision())


@pytest.mark.asyncio
async def test_concurrent_decision_loses_cleanly(service, repo, users, session):
    req = _request(payload={"requested_amount": 1})
    repo.find_by_id.return_value = req
    users.find_by_id.return_value = _user(req.user_id)
    repo.transition.side_effect = None
    repo.transition.return_value = None  # someone else decided in between
    with pytest.raises(ConflictError):
        await service.approve(session, uuid.uuid4(), req.request_id, RequestDecision())
    session.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_submit_race_on_unique_index(service, repo, users, session):
    from sqlalchemy.exc import IntegrityError

    users.find_by_id.return_value = _user(status="active")
    repo.create.side_effect = IntegrityError("dup", {}, Exception())
    with pytest.raises(ConflictError):
        await service.submit_credit_request(session, uuid.uuid4(), 1, None)
    session.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_ensure_signup_request_is_idempotent(service, repo, session, quiet_notifications):
    user = _user()
    existing = _request(rtype=RequestType.SIGNUP_APPROVAL.value, uid=user.user_id)
    repo.find_pending.return_value = existing
    assert await service.ensure_signup_request(session, user) is existing
    repo.create.assert_not_called()
    repo.find_pending.return_value = None
    repo.create.return_value = _request(rtype=RequestType.SIGNUP_APPROVAL.value, uid=user.user_id)
    await service.ensure_signup_request(session, user)
    repo.create.assert_awaited_once()
    quiet_notifications.notify_admins_new_request.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_pending_signup_and_listings(service, repo, session):
    uid = uuid.uuid4()
    pending = _request(rtype=RequestType.SIGNUP_APPROVAL.value, uid=uid)
    repo.find_pending.return_value = pending
    repo.find_by_id.return_value = pending
    await service.resolve_pending_signup(session, uid, None, RequestStatus.AUTO_APPROVED, "policy")
    assert pending.status == "auto_approved"
    repo.list_with_user.return_value = [(pending, "u@example.com", "U")]
    repo.count.return_value = 1
    items, meta = await service.list_for_user(session, uid, None, 0, 10)
    assert items[0].request_id == pending.request_id and meta.total == 1
    items, _ = await service.list_all(session, "pending", None, 0, 10)
    assert items[0].user_email == "u@example.com"
