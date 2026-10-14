"""Job lifecycle (user + training-server side) and group/admin management endpoints."""
import pytest

from tests.conftest import bearer, make_user

INTERNAL = {"X-Api-Key": "test-internal-key"}


async def _job(client, headers):
    sim = (await client.post("/simulators", headers=headers, json={"simulator_name": "S"})).json()["data"]
    res = await client.post("/jobs", headers=headers, json={"simulator_id": sim["simulator_id"], "job_name": "J"})
    assert res.status_code == 200, res.text
    return res.json()["data"]


@pytest.mark.asyncio
async def test_job_cancel_resume_delete_and_training_server_endpoints(client, db_session):
    user = await make_user(db_session, credits=3)
    me = bearer(user)
    job = await _job(client, me)
    jid = job["job_id"]
    assert (await client.get("/users/me", headers=me)).json()["data"]["user_credits"] == 2
    listed = (await client.get("/jobs", headers=me)).json()
    assert listed["data"][0]["job_id"] == jid and listed["metadata"]["total"] == 1

    # user pauses, changes mind, resumes
    assert (await client.post(f"/jobs/{jid}/request-cancel", headers=me)).json()["data"]["paused"] is True
    assert (await client.post(f"/jobs/{jid}/resume", headers=me)).json()["data"]["resumed"] is True
    assert (await client.put(f"/jobs/{jid}", headers=me, json={"job_name": "J2"})).json()["data"]["job_name"] == "J2"

    # training server picks it up
    assert (await client.get("/jobs/admin/by-status", headers=me)).status_code == 401  # JWT is not an API key
    res = await client.get("/jobs/admin/by-status", headers=INTERNAL, params={"statuses": "pending"})
    assert res.status_code == 200 and any(j["job_id"] == jid for j in res.json()["data"])
    res = await client.get(f"/jobs/admin/{jid}", headers=INTERNAL)
    assert res.json()["data"]["user_email"] == user.user_email and res.json()["data"]["result_path"]
    assert (await client.post(f"/jobs/admin/{jid}/claim", headers=INTERNAL, json={"claimed_by": "srv-1"})).status_code == 200
    assert (await client.post(f"/jobs/admin/{jid}/claim", headers=INTERNAL, json={"claimed_by": "srv-2"})).status_code == 409
    # once training, a cancel request no longer pauses and deleting does not refund
    assert (await client.post(f"/jobs/{jid}/request-cancel", headers=me)).json()["data"]["paused"] is False
    res = await client.patch(f"/jobs/admin/{jid}/status", headers=INTERNAL, json={"job_status": "complete"})
    assert res.json()["data"]["job_status"] == "complete"
    res = await client.delete(f"/jobs/{jid}", headers=me)
    assert res.json()["data"] == {"refunded": False, "previous_status": "complete"}

    # a pending job deleted after cancel is refunded
    job2 = await _job(client, me)
    await client.post(f"/jobs/{job2['job_id']}/request-cancel", headers=me)
    assert (await client.delete(f"/jobs/{job2['job_id']}", headers=me)).json()["data"]["refunded"] is True
    assert (await client.get("/users/me", headers=me)).json()["data"]["user_credits"] == 2
    assert (await client.get(f"/jobs/{job2['job_id']}", headers=me)).status_code == 404


@pytest.mark.asyncio
async def test_group_management_and_admin_views(client, db_session, test_user, other_user, admin_user):
    me, other, admin = bearer(test_user), bearer(other_user), bearer(admin_user)
    gid = (await client.post("/groups", headers=me, json={"group_name": "G", "description": "d"})).json()["data"]["group_id"]
    res = await client.patch(f"/groups/{gid}", headers=me, json={"group_name": "G2"})
    assert res.json()["data"]["group_name"] == "G2" and res.json()["data"]["my_role"] == "admin"
    assert (await client.patch(f"/groups/{gid}", headers=other, json={"group_name": "x"})).status_code == 403

    res = await client.post(f"/groups/{gid}/members", headers=me, json={"email": other_user.user_email})
    assert res.status_code == 200
    assert (await client.post(f"/groups/{gid}/members", headers=me, json={"email": other_user.user_email})).status_code == 409
    assert (await client.post(f"/groups/{gid}/members", headers=me, json={"email": "ghost@example.com"})).status_code == 422
    res = await client.patch(f"/groups/{gid}/members/{other_user.user_id}", headers=me, json={"role": "admin"})
    assert {m["role"] for m in res.json()["data"]["members"]} == {"admin"}
    mine = (await client.get("/groups", headers=other)).json()["data"]
    assert mine[0]["group_id"] == gid and mine[0]["member_count"] == 2
    # now the original admin may step down
    assert (await client.patch(f"/groups/{gid}/members/{test_user.user_id}", headers=other, json={"role": "member"})).status_code == 200
    assert (await client.delete(f"/groups/{gid}/members/{other_user.user_id}", headers=me)).status_code == 403
    assert (await client.patch(f"/groups/{gid}/members/{uuid4_str()}", headers=other, json={"role": "member"})).status_code == 404

    # admin console sees every group; platform admins may also manage any group
    res = await client.get("/admin/groups", headers=admin)
    assert res.status_code == 200 and any(g["group_id"] == gid for g in res.json()["data"])
    assert (await client.get(f"/groups/{gid}", headers=admin)).status_code == 200
    assert (await client.get("/admin/groups", headers=me)).status_code == 403

    # share with the group, then delete the group: the grant disappears with it
    eq = (await client.post("/equipment", headers=me, json={"equipment_name": "GE"})).json()["data"]
    await client.post(f"/shares/equipment/{eq['equipment_id']}", headers=me, json={"principal_type": "group", "group_id": gid})
    shares = (await client.get(f"/shares/equipment/{eq['equipment_id']}", headers=me)).json()["data"]
    assert shares[0]["principal_label"] == "G2"
    assert (await client.delete(f"/groups/{gid}", headers=me)).status_code == 403  # demoted to member
    assert (await client.delete(f"/groups/{gid}", headers=other)).status_code == 200
    assert (await client.get(f"/shares/equipment/{eq['equipment_id']}", headers=me)).json()["data"] == []
    assert (await client.get(f"/groups/{gid}", headers=other)).status_code == 404

    # admin user detail includes memberships; unknown user → 404
    res = await client.get(f"/admin/users/{test_user.user_id}", headers=admin)
    assert res.status_code == 200 and res.json()["data"]["groups"] == []
    assert (await client.get(f"/admin/users/{uuid4_str()}", headers=admin)).status_code == 404
    res = await client.get("/admin/users", headers=admin, params={"role": "admin"})
    assert all(u["role"] == "admin" for u in res.json()["data"])


def uuid4_str() -> str:
    import uuid

    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_session_and_profile_endpoints(client, test_user):
    me = bearer(test_user)
    res = await client.put("/users/me", headers=me, json={"user_name": "Renamed", "user_company": "ACME"})
    assert res.json()["data"]["user_name"] == "Renamed"
    res = await client.post("/users/me/consents", headers=me,
                            json={"terms_version": "2026-10-01", "privacy_version": "2026-10-01"})
    assert res.json()["data"]["up_to_date"] is True
    res = await client.post("/users/me/consents", headers=me, json={"terms_version": "old", "privacy_version": "old"})
    assert res.status_code == 422
    res = await client.post("/users/me/credits/purchase", headers=me, json={"quantity": 2})
    assert res.status_code == 200 and res.json()["data"]["user_credits"] == 2
    assert (await client.delete("/users/me", headers=me)).status_code == 200
    assert (await client.get("/users/me", headers=me)).status_code == 401
