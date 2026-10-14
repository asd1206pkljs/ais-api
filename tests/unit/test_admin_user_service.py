import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enums import RequestStatus, UserRole, UserStatus
from app.exceptions import NotFoundError, ValidationError
from app.schemas.admin import AdminUserUpdate, CreditAdjustment
from app.services.admin_user_service import AdminUserService


def _user(uid=None, role="user", status="active", credits=0, token_version=0):
    u = MagicMock()
    u.user_id = uid or uuid.uuid4()
    u.user_name = "U"
    u.user_email = "u@example.com"
    u.user_company = None
    u.user_credits = credits
    u.role = role
    u.status = status
    u.approved = True
    u.joined_at = MagicMock()
    u.last_login_at = None
    u.token_version = token_version
    return u


@pytest.fixture
def users():
    return AsyncMock()


@pytest.fixture
def groups():
    g = AsyncMock()
    g.find_for_user.return_value = []
    return g


@pytest.fixture
def requests():
    return AsyncMock()


@pytest.fixture
def service(users, groups, requests):
    return AdminUserService(users, groups, requests, AsyncMock())


@pytest.fixture(autouse=True)
def quiet():
    with patch("app.services.admin_user_service.notifications") as n:
        yield n


@pytest.mark.asyncio
async def test_list_and_get(service, users):
    users.search.return_value = [_user()]
    users.count_search.return_value = 1
    items, meta = await service.list_users(AsyncMock(), status=None, role=None, q=None, skip=0, limit=10)
    assert items[0].user_email == "u@example.com" and meta.total == 1
    users.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_user(AsyncMock(), uuid.uuid4())


@pytest.mark.asyncio
async def test_cannot_demote_or_disable_self(service, users):
    admin = _user(role="admin")
    users.find_by_id.return_value = admin
    with pytest.raises(ValidationError):
        await service.update_user(AsyncMock(), admin.user_id, admin.user_id, AdminUserUpdate(role=UserRole.USER))
    with pytest.raises(ValidationError):
        await service.update_user(AsyncMock(), admin.user_id, admin.user_id,
                                  AdminUserUpdate(status=UserStatus.DISABLED))


@pytest.mark.asyncio
async def test_activate_resolves_signup_request_and_notifies(service, users, requests, quiet):
    admin, target = uuid.uuid4(), _user(status="pending_approval")
    users.find_by_id.return_value = target
    users.update.return_value = _user(target.user_id, status="active")
    session = AsyncMock()
    read = await service.update_user(session, admin, target.user_id, AdminUserUpdate(status=UserStatus.ACTIVE, note="ok"))
    assert users.update.call_args[0][2] == {"status": "active"}
    requests.resolve_pending_signup.assert_awaited_once_with(session, target.user_id, admin, RequestStatus.APPROVED, "ok")
    quiet.notify_user_account_activated.assert_called_once()
    assert read.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_disable_bumps_token_version_and_role_change(service, users, requests, quiet):
    admin, target = uuid.uuid4(), _user(token_version=3)
    users.find_by_id.return_value = target
    users.update.return_value = _user(target.user_id, status="disabled", role="admin")
    await service.update_user(AsyncMock(), admin, target.user_id,
                              AdminUserUpdate(status=UserStatus.DISABLED, role=UserRole.ADMIN))
    assert users.update.call_args[0][2] == {"role": "admin", "status": "disabled", "token_version": 4}
    quiet.notify_user_account_disabled.assert_called_once()
    # no-op when nothing changes
    users.update.reset_mock()
    users.find_by_id.return_value = _user(role="admin")
    await service.update_user(AsyncMock(), admin, uuid.uuid4(), AdminUserUpdate(role=UserRole.ADMIN))
    users.update.assert_not_called()


@pytest.mark.asyncio
async def test_adjust_credits(service, users):
    target = _user(credits=2)
    users.find_by_id.return_value = target
    with pytest.raises(ValidationError):
        await service.adjust_credits(AsyncMock(), uuid.uuid4(), target.user_id, CreditAdjustment(amount=-5, reason="x"))
    await service.adjust_credits(AsyncMock(), uuid.uuid4(), target.user_id, CreditAdjustment(amount=3, reason="top-up"))
    users.refund_credit.assert_awaited_once_with(users.refund_credit.call_args[0][0], target.user_id, 3)
