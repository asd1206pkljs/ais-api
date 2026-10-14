"""HTTP-level tests for cookie sessions, revocation, lockout and reset enumeration."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from tests.conftest import CONSENTS
from jose import jwt

from app.config import settings
from app.services.auth_service import hash_password

SEND_RESET = "app.services.password_reset_service.send_password_reset_email"
SEND_VERIFY = "app.services.email_verification_service.send_verification_email"
PASSWORD = "password123"  # conftest test_user's password


def _cookie_headers(res, name: str) -> list[str]:
    return [c for c in res.headers.get_list("set-cookie") if c.startswith(f"{name}=")]


async def _login(client, email, password=PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


# --- cookie session + logout revocation ---------------------------------------


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie_and_logout_revokes(client, test_user):
    res = await _login(client, test_user.user_email)
    assert res.status_code == 200, res.text
    (access,) = _cookie_headers(res, settings.AUTH_COOKIE_NAME)
    (marker,) = _cookie_headers(res, settings.LOGGED_IN_COOKIE_NAME)
    assert "HttpOnly" in access and "SameSite=lax" in access and "Path=/" in access
    assert "HttpOnly" not in marker  # readable marker carries no secret
    body_token = res.json()["data"]["access_token"]

    # Cookie alone authenticates (httpx keeps the jar; no Authorization header).
    res = await client.get("/users/me")
    assert res.status_code == 200, res.text

    res = await client.post("/auth/logout")
    assert res.status_code == 200
    assert client.cookies.get(settings.AUTH_COOKIE_NAME) is None
    assert client.cookies.get(settings.LOGGED_IN_COOKIE_NAME) is None

    res = await client.get("/users/me")
    assert res.status_code == 401

    # The same token is dead even if someone kept a copy and sends it as Bearer.
    res = await client.get("/users/me", headers={"Authorization": f"Bearer {body_token}"})
    assert res.status_code == 401
    assert res.json()["error"] == "Token has been revoked"


@pytest.mark.asyncio
async def test_logout_without_session_still_succeeds(client):
    res = await client.post("/auth/logout")
    assert res.status_code == 200


# --- password change kills other sessions ----------------------------------------


@pytest.mark.asyncio
async def test_password_change_invalidates_other_sessions_but_keeps_current(client, test_user):
    token_a = (await _login(client, test_user.user_email)).json()["data"]["access_token"]
    token_b = (await _login(client, test_user.user_email)).json()["data"]["access_token"]

    res = await client.post("/users/me/password", json={
        "current_password": PASSWORD, "new_password": "Changed456!",
    })
    assert res.status_code == 200, res.text
    assert _cookie_headers(res, settings.AUTH_COOKIE_NAME)  # fresh cookie issued

    for old in (token_a, token_b):
        res = await client.get("/users/me", headers={"Authorization": f"Bearer {old}"})
        assert res.status_code == 401
        assert res.json()["error"] == "Session is no longer valid"

    # This browser continues with the refreshed cookie.
    res = await client.get("/users/me")
    assert res.status_code == 200, res.text


# --- lockout ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lockout_after_repeated_failures_and_reset_unlocks(client, test_user):
    email = test_user.user_email
    for i in range(settings.LOGIN_MAX_FAILURES):
        res = await _login(client, email, "Wrong123!")
        if i < settings.LOGIN_MAX_FAILURES - 1:
            assert res.status_code == 401, (i, res.text)
        else:
            assert res.status_code == 429, (i, res.text)
            assert int(res.headers["Retry-After"]) > 0

    # Even the right password is refused while locked.
    res = await _login(client, email)
    assert res.status_code == 429

    # Resetting the password unlocks the account and invalidates old sessions.
    with patch(SEND_RESET) as send:
        res = await client.post("/auth/forgot-password", json={"email": email})
    assert res.status_code == 200
    reset_url = send.call_args[0][1]
    token = parse_qs(urlparse(reset_url).query)["token"][0]
    res = await client.post("/auth/reset-password", json={"token": token, "new_password": "Fresh789!"})
    assert res.status_code == 200, res.text

    res = await _login(client, email, "Fresh789!")
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_lockout_applies_to_unknown_emails_too(client):
    # Same behaviour for emails that don't exist, so 429 reveals nothing.
    email = f"nobody_{uuid.uuid4().hex[:8]}@example.com"
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        assert (await _login(client, email, "Wrong123!")).status_code == 401
    assert (await _login(client, email, "Wrong123!")).status_code == 429


# --- forgot-password never reveals registration status ----------------------------


@pytest.mark.asyncio
async def test_forgot_password_is_generic_for_unknown_and_pending_emails(client):
    with patch(SEND_RESET) as send:
        res = await client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
    assert res.status_code == 200
    assert res.json()["data"]["message"].startswith("If an account exists")
    send.assert_not_called()

    pending = f"pending_{uuid.uuid4().hex[:8]}@example.com"
    with patch(SEND_VERIFY):
        res = await client.post("/auth/register", json={
            "user_name": "P", "email": pending, "password": "Password123!", "consents": CONSENTS,
        })
    assert res.status_code == 200, res.text
    with patch(SEND_RESET) as send:
        res = await client.post("/auth/forgot-password", json={"email": pending})
    assert res.status_code == 200
    send.assert_not_called()


# --- token validation edge cases --------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_token_without_jti_is_rejected(client, test_user):
    legacy = jwt.encode(
        {"sub": str(test_user.user_id), "email": test_user.user_email,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM,
    )
    res = await client.get("/users/me", headers={"Authorization": f"Bearer {legacy}"})
    assert res.status_code == 401
    assert res.json()["error"] == "Invalid token payload"


@pytest.mark.asyncio
async def test_token_for_unverified_user_is_rejected(client, db_session):
    from app.repositories.user_repository import UserRepository
    from app.services.auth_service import create_access_token

    pending = await UserRepository().create(db_session, {
        "user_id": uuid.uuid4(), "user_name": "Pending",
        "user_email": f"pend_{uuid.uuid4().hex[:8]}@example.com",
        "user_password": hash_password(PASSWORD), "approved": False,
    })
    token = create_access_token(pending.user_id, pending.user_email, pending.token_version)
    res = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["error"] == "Email not verified"
