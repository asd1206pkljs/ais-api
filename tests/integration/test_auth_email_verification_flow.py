"""End-to-end sign-up → verify → login flow over HTTP against the test DB."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from tests.conftest import CONSENTS
from sqlalchemy import select

from app.models.user import User

SEND = "app.services.email_verification_service.send_verification_email"
PASSWORD = "Password123!"


def _token_from(send_mock) -> str:
    url = send_mock.call_args[0][1]
    return parse_qs(urlparse(url).query)["token"][0]


async def _rows_for(db_session, email: str) -> list[User]:
    result = await db_session.execute(select(User).where(User.user_email == email))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_signup_requires_email_verification_before_login(client, db_session):
    email = "flow.user@auto.example.com"  # allow-listed domain: active right after verification

    # 1. Sign up with mixed-case email → stored lowercase, unverified, no token issued.
    with patch(SEND) as send:
        res = await client.post("/auth/register", json={
            "user_name": "Flow", "email": "Flow.User@Auto.Example.COM", "password": PASSWORD, "consents": CONSENTS,
        })
    assert res.status_code == 200, res.text
    assert "access_token" not in res.json()["data"]
    assert send.call_args[0][0] == email
    token = _token_from(send)
    (user,) = await _rows_for(db_session, email)
    assert user.approved is False

    # 2. Correct password but unverified → 403 with a stable, code-friendly message.
    res = await client.post("/auth/login", json={"email": "FLOW.USER@auto.example.com", "password": PASSWORD})
    assert res.status_code == 403
    assert res.json()["error"] == "Email not verified"

    # 3. Wrong password → generic 401 (must not reveal the pending sign-up).
    res = await client.post("/auth/login", json={"email": email, "password": "Wrong123!"})
    assert res.status_code == 401
    assert res.json()["error"] == "Invalid email or password"

    # 4. Someone else (or the same person) may sign up again while unverified.
    with patch(SEND):
        res = await client.post("/auth/register", json={
            "user_name": "Flow2", "email": email, "password": "Other456!", "consents": CONSENTS,
        })
    assert res.status_code == 200, res.text
    assert len(await _rows_for(db_session, email)) == 2

    # 5. Clicking the first link approves that account and removes the other pending one.
    res = await client.post("/auth/verify-email", json={"token": token})
    assert res.status_code == 200, res.text
    db_session.expire_all()
    (user,) = await _rows_for(db_session, email)
    assert user.approved is True
    assert user.user_name == "Flow"

    # 6. Now login works (any case) and the token is accepted by protected routes.
    res = await client.post("/auth/login", json={"email": "Flow.User@Auto.Example.com", "password": PASSWORD})
    assert res.status_code == 200, res.text
    access = res.json()["data"]["access_token"]
    res = await client.get("/users/me", headers={"Authorization": f"Bearer {access}"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["approved"] is True

    # 7. A verified email can no longer be registered again — in any case.
    with patch(SEND) as send:
        res = await client.post("/auth/register", json={
            "user_name": "Dup", "email": "flow.USER@auto.example.com", "password": PASSWORD, "consents": CONSENTS,
        })
    assert res.status_code == 409
    send.assert_not_called()

    # 8. Re-clicking the link is harmless.
    res = await client.post("/auth/verify-email", json={"token": token})
    assert res.status_code == 200

    # 9. Resend for an already-verified email is a silent no-op.
    with patch(SEND) as send:
        res = await client.post("/auth/resend-verification", json={"email": email})
    assert res.status_code == 200
    send.assert_not_called()


@pytest.mark.asyncio
async def test_resend_verification_targets_pending_signup(client, db_session):
    email = "pending.only@example.com"
    with patch(SEND):
        res = await client.post("/auth/register", json={
            "user_name": "P", "email": email, "password": PASSWORD, "consents": CONSENTS,
        })
    assert res.status_code == 200, res.text

    with patch(SEND) as send:
        res = await client.post("/auth/resend-verification", json={"email": email.upper()})
    assert res.status_code == 200
    assert send.call_args[0][0] == email
    assert _token_from(send)  # a fresh, valid link was issued


@pytest.mark.asyncio
async def test_verify_email_rejects_bad_token(client):
    res = await client.post("/auth/verify-email", json={"token": "garbage"})
    assert res.status_code == 422
    assert res.json()["error"] == "Invalid or expired verification link"


@pytest.mark.asyncio
async def test_register_rolls_back_when_email_cannot_be_sent(client, db_session):
    email = "unsendable@example.com"
    with patch(SEND, side_effect=RuntimeError("smtp down")):
        res = await client.post("/auth/register", json={
            "user_name": "U", "email": email, "password": PASSWORD, "consents": CONSENTS,
        })
    assert res.status_code == 500
    assert await _rows_for(db_session, email) == []
