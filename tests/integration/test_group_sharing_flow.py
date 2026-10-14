"""Data separation between users, sharing by email/group/public, admin limits."""
import pytest

from app.config import settings
from app.services.crypto import is_encrypted
from tests.conftest import bearer, make_user

CONFIG = {"equipment_name": "E1", "cluster_type": "single_cluster", "modules": [], "timetables": {}}


async def _create_equipment(client, headers, name="E1"):
    res = await client.post("/equipment", headers=headers, json={"equipment_name": name})
    assert res.status_code == 200, res.text
    return res.json()["data"]


@pytest.mark.asyncio
async def test_other_users_cannot_see_my_equipment(client, test_user, other_user, db_session):
    me, other = bearer(test_user), bearer(other_user)
    eq = await _create_equipment(client, me)
    assert "equipment_configuration_file_path" not in eq  # no server paths in responses

    # Stored config is encrypted on disk.
    from app.repositories.equipment_repository import EquipmentRepository
    row = await EquipmentRepository().find_by_id(db_session, eq["equipment_id"])
    with open(row.equipment_configuration_file_path, "rb") as f:
        assert is_encrypted(f.read())

    eid = eq["equipment_id"]
    assert (await client.get(f"/equipment/{eid}", headers=other)).status_code == 403
    assert (await client.get(f"/equipment/{eid}/config", headers=other)).status_code == 403
    assert (await client.put(f"/equipment/{eid}/config", headers=other, json=CONFIG)).status_code == 403
    assert (await client.post(f"/equipment/{eid}/copy", headers=other, json={"equipment_name": "x"})).status_code == 403
    listed = (await client.get("/equipment", headers=other)).json()["data"]
    assert all(e["equipment_id"] != eid for e in listed)
    assert (await client.get(f"/shares/equipment/{eid}", headers=other)).status_code == 403


@pytest.mark.asyncio
async def test_share_with_user_by_email_view_then_edit(client, test_user, other_user):
    me, other = bearer(test_user), bearer(other_user)
    eid = (await _create_equipment(client, me))["equipment_id"]

    res = await client.post(f"/shares/equipment/{eid}", headers=me, json={
        "principal_type": "user", "email": other_user.user_email.upper(), "permission": "view"})
    assert res.status_code == 200, res.text
    share = res.json()["data"]
    assert share["principal_label"] == other_user.user_email and share["permission"] == "view"

    assert (await client.get(f"/equipment/{eid}/config", headers=other)).status_code == 200
    assert (await client.put(f"/equipment/{eid}/config", headers=other, json=CONFIG)).status_code == 403
    assert (await client.delete(f"/equipment/{eid}", headers=other)).status_code == 403
    listed = (await client.get("/equipment", headers=other)).json()["data"]
    mine = next(e for e in listed if e["equipment_id"] == eid)
    assert str(other_user.user_id) in mine["viewers"] and str(other_user.user_id) not in mine["editors"]

    res = await client.post(f"/shares/equipment/{eid}", headers=me, json={
        "principal_type": "user", "user_id": str(other_user.user_id), "permission": "edit"})
    assert res.status_code == 200
    assert (await client.put(f"/equipment/{eid}/config", headers=other, json=CONFIG)).status_code == 200

    shares = (await client.get(f"/shares/equipment/{eid}", headers=me)).json()["data"]
    assert len(shares) == 1 and shares[0]["permission"] == "edit"
    res = await client.delete(f"/shares/equipment/{eid}/{shares[0]['share_id']}", headers=me)
    assert res.status_code == 200
    assert (await client.get(f"/equipment/{eid}/config", headers=other)).status_code == 403

    # Unknown / pending accounts cannot be targeted, nor the owner.
    res = await client.post(f"/shares/equipment/{eid}", headers=me, json={
        "principal_type": "user", "email": "nobody@example.com"})
    assert res.status_code == 422
    res = await client.post(f"/shares/equipment/{eid}", headers=me, json={
        "principal_type": "user", "email": test_user.user_email})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_legacy_viewer_editor_endpoints_still_work(client, test_user, other_user):
    me, other = bearer(test_user), bearer(other_user)
    eid = (await _create_equipment(client, me))["equipment_id"]
    uid = str(other_user.user_id)
    res = await client.post(f"/equipment/{eid}/editors", headers=me, json={"user_id": uid})
    assert res.status_code == 200 and uid in res.json()["data"]["editors"]
    assert (await client.put(f"/equipment/{eid}/config", headers=other, json=CONFIG)).status_code == 200
    res = await client.delete(f"/equipment/{eid}/editors/{uid}", headers=me)
    assert uid in res.json()["data"]["viewers"] and uid not in res.json()["data"]["editors"]
    res = await client.delete(f"/equipment/{eid}/viewers/{uid}", headers=me)
    assert uid not in res.json()["data"]["viewers"]
    # "*" is no longer something an owner can hand out.
    res = await client.post(f"/equipment/{eid}/viewers", headers=me, json={"user_id": "*"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_group_sharing_and_isolation(client, test_user, other_user, db_session):
    me, member = bearer(test_user), bearer(other_user)
    outsider = bearer(await make_user(db_session, name="Outsider"))

    res = await client.post("/groups", headers=me, json={"group_name": "Acme"})
    assert res.status_code == 200, res.text
    gid = res.json()["data"]["group_id"]
    assert res.json()["data"]["my_role"] == "admin"

    res = await client.post(f"/groups/{gid}/members", headers=me, json={"email": other_user.user_email})
    assert res.status_code == 200, res.text
    assert {m["user_email"] for m in res.json()["data"]["members"]} == {test_user.user_email, other_user.user_email}
    assert (await client.post(f"/groups/{gid}/members", headers=member,
                              json={"email": "x@example.com"})).status_code == 403  # members cannot add
    assert (await client.get(f"/groups/{gid}", headers=outsider)).status_code == 403

    res = await client.post("/simulators", headers=me, json={"simulator_name": "S"})
    sid = res.json()["data"]["simulator_id"]
    assert "simulator_path" not in res.json()["data"]
    assert (await client.get(f"/simulators/{sid}/config", headers=member)).status_code == 403

    res = await client.post(f"/shares/simulator/{sid}", headers=me, json={"principal_type": "group", "group_id": gid})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["principal_label"] == "Acme"
    assert (await client.get(f"/simulators/{sid}/config", headers=member)).status_code == 200
    assert (await client.get(f"/simulators/{sid}/config", headers=outsider)).status_code == 403
    sims = (await client.get("/simulators", headers=member)).json()["data"]
    assert any(s["simulator_id"] == sid for s in sims)

    # Outsider cannot share into a group they do not belong to.
    res = await client.post("/equipment", headers=outsider, json={"equipment_name": "X"})
    xid = res.json()["data"]["equipment_id"]
    res = await client.post(f"/shares/equipment/{xid}", headers=outsider,
                            json={"principal_type": "group", "group_id": gid})
    assert res.status_code == 403

    # Leaving the group removes the access.
    res = await client.delete(f"/groups/{gid}/members/{other_user.user_id}", headers=member)
    assert res.status_code == 200
    assert (await client.get(f"/simulators/{sid}/config", headers=member)).status_code == 403
    # The last admin cannot leave.
    assert (await client.delete(f"/groups/{gid}/members/{test_user.user_id}", headers=me)).status_code == 409
    perms = (await client.get("/users/me/permissions", headers=me)).json()["data"]
    assert perms["groups"] == [{"group_id": gid, "group_name": "Acme", "role": "admin"}]


@pytest.mark.asyncio
async def test_public_sharing_is_admin_controlled(client, test_user, other_user, admin_user):
    me, other, admin = bearer(test_user), bearer(other_user), bearer(admin_user)
    eid = (await _create_equipment(client, me))["equipment_id"]

    res = await client.post(f"/shares/equipment/{eid}", headers=me, json={"principal_type": "public"})
    assert res.status_code == 403
    res = await client.post(f"/shares/equipment/{eid}", headers=admin, json={"principal_type": "public"})
    assert res.status_code == 200, res.text
    assert (await client.get(f"/equipment/{eid}/config", headers=other)).status_code == 200
    listed = (await client.get("/equipment", headers=other)).json()["data"]
    assert "*" in next(e for e in listed if e["equipment_id"] == eid)["viewers"]

    res = await client.get("/admin/shares", headers=admin, params={"public_only": "true"})
    rows = [s for s in res.json()["data"] if s["resource_id"] == eid]
    assert rows and rows[0]["resource_name"] == "E1" and rows[0]["owner_id"] == str(test_user.user_id)
    assert (await client.delete(f"/admin/shares/{rows[0]['share_id']}", headers=admin)).status_code == 200
    assert (await client.get(f"/equipment/{eid}/config", headers=other)).status_code == 403


@pytest.mark.asyncio
async def test_admin_sees_metadata_but_not_content(client, test_user, admin_user):
    me, admin = bearer(test_user), bearer(admin_user)
    eid = (await _create_equipment(client, me, "Secret"))["equipment_id"]
    listed = (await client.get("/equipment", headers=admin)).json()["data"]
    assert any(e["equipment_id"] == eid for e in listed)
    assert (await client.get(f"/equipment/{eid}", headers=admin)).status_code == 200
    assert (await client.get(f"/equipment/{eid}/config", headers=admin)).status_code == 403
    assert (await client.post(f"/equipment/{eid}/copy", headers=admin, json={"equipment_name": "c"})).status_code == 403
    # Admins can see (and revoke) shares of any resource.
    assert (await client.get(f"/shares/equipment/{eid}", headers=admin)).status_code == 200
    assert settings.ENCRYPT_DATA_AT_REST is True
