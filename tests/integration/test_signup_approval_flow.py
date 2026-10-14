"""Sign-up → verify → (approval policy) → login, plus admin account controls."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.models.user import User
from tests.conftest import CONSENTS, bearer, make_user

SEND = "app.services.email_verification_service.send_verification_email"
PASSWORD = "Password123!"


def _token_from(send_mock) -> str:
    return parse_qs(urlparse(send_mock.call_args[0][1]).query)["token"][0]


async def _register_and_verify(client, email):
    with patch(SEND) as send:
        res = await client.post("/auth/register", json={
            "user_name": "New", "email": email, "password": PASSWORD, "consents": CONSENTS,
        })
    assert res.status_code == 200, res.text
    res = await client.post("/auth/verify-email", json={"token": _token_from(send)})
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_registration_requires_current_consent(client):
    res = await client.post("/auth/register", json={
        "user_name": "No Consent", "email": "noconsent@example.com", "password": PASSWORD,
    })
    assert res.status_code == 422
    assert "Terms" in res.json()["error"]
    res = await client.post("/auth/register", json={
        "user_name": "Old", "email": "old@example.com", "password": PASSWORD,
        "consents": {"terms_version": "2000-01-01", "privacy_version": "2026-10-01"},
    })
    assert res.status_code == 422
    res = await client.get("/legal/versions")
    assert res.json()["data"] == {"terms_version": "2026-10-01", "privacy_version": "2026-10-01",
                                  "consent_required": True}


@pytest.mark.asyncio
async def test_verified_signup_waits_for_admin_approval(client, db_session, admin_user):
    email = "pending.user@example.com"
    await _register_and_verify(client, email)

    (user,) = (await db_session.execute(select(User).where(User.user_email == email))).scalars().all()
    assert user.approved is True and user.status == "pending_approval"

    res = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 403 and res.json()["error"] == "Account awaiting approval"

    # Consent history was kept with the sign-up.
    res = await client.get("/admin/requests", headers=bearer(admin_user), params={"request_type": "signup_approval"})
    assert res.status_code == 200, res.text
    pending = [r for r in res.json()["data"] if r["user_email"] == email]
    assert len(pending) == 1 and pending[0]["status"] == "pending"

    res = await client.post(f"/admin/requests/{pending[0]['request_id']}/approve",
                            headers=bearer(admin_user), json={"note": "welcome"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "approved"

    res = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    me = (await client.get("/users/me")).json()["data"]
    assert me["status"] == "active" and me["role"] == "user"
    perms = (await client.get("/users/me/permissions")).json()["data"]
    assert perms["is_admin"] is False and perms["consent_up_to_date"] is True and perms["groups"] == []
    consents = (await client.get("/users/me/consents")).json()["data"]
    assert consents["accepted_terms_version"] == "2026-10-01"

    # Approving twice is refused.
    res = await client.post(f"/admin/requests/{pending[0]['request_id']}/approve", headers=bearer(admin_user))
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_allow_listed_domain_is_activated_by_policy(client):
    email = "auto.user@auto.example.com"
    await _register_and_verify(client, email)
    res = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    reqs = (await client.get("/users/me/requests")).json()["data"]
    assert reqs == []  # nothing needed an administrator


@pytest.mark.asyncio
async def test_admin_can_disable_and_reactivate_accounts(client, db_session, admin_user):
    victim = await make_user(db_session)
    headers = bearer(victim)
    assert (await client.get("/users/me", headers=headers)).status_code == 200

    res = await client.patch(f"/admin/users/{victim.user_id}", headers=bearer(admin_user),
                             json={"status": "disabled", "note": "policy"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "disabled"
    # Existing sessions die immediately; new logins are refused with a clear reason.
    assert (await client.get("/users/me", headers=headers)).status_code == 401
    res = await client.post("/auth/login", json={"email": victim.user_email, "password": "password123"})
    assert res.status_code == 403 and res.json()["error"] == "Account disabled"

    res = await client.patch(f"/admin/users/{victim.user_id}", headers=bearer(admin_user), json={"status": "active"})
    assert res.status_code == 200
    res = await client.post("/auth/login", json={"email": victim.user_email, "password": "password123"})
    assert res.status_code == 200, res.text

    # Roles are managed server-side; the change shows up in the user's permissions.
    res = await client.patch(f"/admin/users/{victim.user_id}", headers=bearer(admin_user), json={"role": "admin"})
    assert res.json()["data"]["role"] == "admin"
    assert (await client.get("/users/me/permissions")).json()["data"]["is_admin"] is True


@pytest.mark.asyncio
async def test_admin_endpoints_need_admin_role(client, test_user, admin_user):
    assert (await client.get("/admin/users", headers=bearer(test_user))).status_code == 403
    assert (await client.get("/admin/users")).status_code == 401
    res = await client.get("/admin/users", headers=bearer(admin_user), params={"q": test_user.user_email})
    assert res.status_code == 200 and res.json()["data"][0]["user_id"] == str(test_user.user_id)
    assert "user_password" not in res.json()["data"][0]
    res = await client.patch(f"/admin/users/{admin_user.user_id}", headers=bearer(admin_user), json={"role": "user"})
    assert res.status_code == 422  # cannot demote yourself
    stats = (await client.get("/admin/stats", headers=bearer(admin_user))).json()["data"]
    assert stats["users_total"] >= 2
