"""Credit requests, admin decisions, credit adjustments and the audit trail."""
import pytest
from sqlalchemy import text

from tests.conftest import bearer, make_user


@pytest.mark.asyncio
async def test_credit_request_lifecycle(client, db_session, admin_user):
    user = await make_user(db_session, credits=0)
    me, admin = bearer(user), bearer(admin_user)

    res = await client.post("/users/me/credit-request", headers=me, json={"requested_amount": 5, "reason": "demo"})
    assert res.status_code == 200, res.text
    req = res.json()["data"]
    assert req["status"] == "pending" and req["payload"]["requested_amount"] == 5
    assert (await client.post("/users/me/credit-request", headers=me, json={"requested_amount": 1})).status_code == 409

    mine = (await client.get("/users/me/requests", headers=me)).json()["data"]
    assert [r["request_id"] for r in mine] == [req["request_id"]]
    assert (await client.get("/admin/requests", headers=me)).status_code == 403

    res = await client.get("/admin/requests", headers=admin, params={"request_type": "credit"})
    found = next(r for r in res.json()["data"] if r["request_id"] == req["request_id"])
    assert found["user_email"] == user.user_email

    res = await client.post(f"/admin/requests/{req['request_id']}/approve", headers=admin,
                            json={"granted_amount": 3, "note": "partial"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "approved" and res.json()["data"]["payload"]["granted_amount"] == 3
    assert (await client.get("/users/me", headers=me)).json()["data"]["user_credits"] == 3
    mine = (await client.get("/users/me/requests", headers=me, params={"status": "approved"})).json()["data"]
    assert mine[0]["decision_note"] == "partial"

    res = await client.post("/users/me/credit-request", headers=me, json={"requested_amount": 2})
    rid = res.json()["data"]["request_id"]
    res = await client.post(f"/admin/requests/{rid}/reject", headers=admin, json={"note": "no"})
    assert res.json()["data"]["status"] == "rejected"
    assert (await client.get("/users/me", headers=me)).json()["data"]["user_credits"] == 3

    # Direct admin adjustment with a reason.
    res = await client.post(f"/admin/users/{user.user_id}/credits", headers=admin,
                            json={"amount": -1, "reason": "refund correction"})
    assert res.status_code == 200 and res.json()["data"]["user_credits"] == 2
    res = await client.post(f"/admin/users/{user.user_id}/credits", headers=admin,
                            json={"amount": -10, "reason": "too much"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_audit_trail_is_queryable_and_immutable(client, db_session, admin_user, test_user):
    me, admin = bearer(test_user), bearer(admin_user)
    res = await client.post("/equipment", headers=me, json={"equipment_name": "Audited"})
    eid = res.json()["data"]["equipment_id"]
    await client.post("/auth/login", json={"email": test_user.user_email, "password": "wrong-pass-1!"})

    res = await client.get("/admin/audit-logs", headers=admin,
                           params={"resource_type": "equipment", "resource_id": eid})
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert rows[0]["action"] == "resource.created" and rows[0]["actor_email"] == test_user.user_email
    assert rows[0]["request_id"] and rows[0]["ip_address"]

    res = await client.get("/admin/audit-logs", headers=admin,
                           params={"action": "auth.login.failure", "outcome": "failure"})
    assert any(r["details"]["email"] == test_user.user_email for r in res.json()["data"])
    res = await client.get("/admin/audit-logs", headers=admin, params={"action_prefix": "resource."})
    assert res.json()["metadata"]["total"] >= 1
    assert (await client.get("/admin/audit-logs", headers=me)).status_code == 403

    # Rows cannot be changed or removed, even by the application's own DB role.
    for stmt in ("UPDATE audit_logs SET action = 'x' WHERE log_id = :id", "DELETE FROM audit_logs WHERE log_id = :id"):
        with pytest.raises(Exception, match="append-only"):
            await db_session.execute(text(stmt), {"id": rows[0]["log_id"]})
        await db_session.rollback()
