import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enums import UserStatus
from app.services.activation_service import ActivationService, auto_approves


def _user(email="u@corp.com", status="pending_approval"):
    u = MagicMock()
    u.user_id = uuid.uuid4()
    u.user_email = email
    u.status = status
    return u


def test_auto_approves_policy():
    with patch("app.services.activation_service.settings") as s:
        s.SIGNUP_REQUIRE_APPROVAL = False
        assert auto_approves("anyone@x.com")
        s.SIGNUP_REQUIRE_APPROVAL = True
        s.signup_auto_approve_domains = {"corp.com"}
        assert auto_approves("Me@CORP.com")
        assert not auto_approves("me@other.com")
        assert not auto_approves("garbage")


@pytest.mark.asyncio
async def test_verified_user_activated_when_policy_allows():
    users, requests = AsyncMock(), AsyncMock()
    svc = ActivationService(users, requests, AsyncMock())
    user = _user()
    with patch("app.services.activation_service.auto_approves", return_value=True), \
         patch("app.services.activation_service.notifications") as n:
        assert await svc.on_email_verified(AsyncMock(), user) == UserStatus.ACTIVE.value
    users.update.assert_awaited_once()
    assert users.update.call_args[0][2] == {"status": "active"}
    requests.resolve_pending_signup.assert_awaited_once()
    n.notify_user_account_activated.assert_called_once_with("u@corp.com")


@pytest.mark.asyncio
async def test_verified_user_queued_for_approval_otherwise():
    users, requests = AsyncMock(), AsyncMock()
    svc = ActivationService(users, requests, AsyncMock())
    user = _user()
    with patch("app.services.activation_service.auto_approves", return_value=False), \
         patch("app.services.activation_service.notifications") as n:
        assert await svc.on_email_verified(AsyncMock(), user) == UserStatus.PENDING_APPROVAL.value
    assert users.update.call_args[0][2] == {"status": "pending_approval"}
    requests.ensure_signup_request.assert_awaited_once_with(users.update.call_args[0][0], user)
    n.notify_user_account_pending.assert_called_once_with("u@corp.com")


@pytest.mark.asyncio
async def test_already_active_is_untouched():
    users = AsyncMock()
    svc = ActivationService(users, AsyncMock(), AsyncMock())
    assert await svc.on_email_verified(AsyncMock(), _user(status="active")) == "active"
    users.update.assert_not_called()
