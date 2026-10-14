"""Simulator lifecycle over HTTP, including eqp_model generation/bundle and the
internal (API-key) entry points used by training servers."""
import io
import tarfile

import pytest

from tests.conftest import bearer, make_user

INTERNAL = {"X-Api-Key": "test-internal-key"}


def _modules(mod_ids):
    lp, ll, pm, r1, r2 = mod_ids
    return [
        {"module_id": lp, "module_type": "loadport", "cluster": ["efem"]},
        {"module_id": ll, "module_type": "loadlock", "cluster": ["efem", "vacuum_cluster_1"]},
        {"module_id": pm, "module_type": "process_module", "cluster": ["vacuum_cluster_1"]},
        {"module_id": r1, "module_type": "robot", "cluster": ["efem"]},
        {"module_id": r2, "module_type": "robot", "cluster": ["vacuum_cluster_1"]},
    ]


async def _build_equipment(client, headers):
    """Equipment with modules, one process recipe and one flow recipe referencing them."""
    ids = []
    for mtype in ("loadport", "loadlock", "process_module", "robot", "robot"):
        res = await client.post("/modules", headers=headers, json={"module_name": mtype, "module_type": mtype})
        ids.append(res.json()["data"]["module_id"])
    lp, ll, pm, r1, r2 = ids
    pr = (await client.post("/process-recipes", headers=headers, json={"process_recipe_name": "P"})).json()["data"]
    res = await client.put(f"/process-recipes/{pr['process_recipe_id']}/config", headers=headers, json={
        "process_recipe_name": "P", "user_added_process_modules": [pm], "process_time": {str(pm): 12.0}})
    assert res.status_code == 200, res.text
    fr = (await client.post("/flow-recipes", headers=headers, json={"flow_recipe_name": "F"})).json()["data"]
    res = await client.put(f"/flow-recipes/{fr['flow_recipe_id']}/config", headers=headers, json={
        "flow_recipe_name": "F", "num_process_steps": 1,
        "process_recipe_steps": [{"step": 1, "process_recipe_id": pr["process_recipe_id"]}],
        "module_sequence": [[str(lp)], [str(ll)], [str(pm)], [str(ll)], [str(lp)]]})
    assert res.status_code == 200, res.text
    eq = (await client.post("/equipment", headers=headers, json={"equipment_name": "GenEq"})).json()["data"]
    res = await client.put(f"/equipment/{eq['equipment_id']}/config", headers=headers, json={
        "equipment_name": "GenEq", "cluster_type": "single_cluster", "modules": _modules(ids), "timetables": {},
        "flow_recipe_ids": [fr["flow_recipe_id"]], "process_recipe_ids": [pr["process_recipe_id"]]})
    assert res.status_code == 200, res.text
    return eq["equipment_id"], fr["flow_recipe_id"]


@pytest.mark.asyncio
async def test_simulator_crud_copy_and_sharing(client, test_user, other_user):
    me, other = bearer(test_user), bearer(other_user)
    sim = (await client.post("/simulators", headers=me, json={"simulator_name": "S"})).json()["data"]
    sid = sim["simulator_id"]
    assert sim["viewers"] == [] and sim["owner_id"] == str(test_user.user_id)

    res = await client.put(f"/simulators/{sid}/config", headers=me,
                           json={"selected_flow_recipe_ids": ["x"], "module_time_configs": {"1": {"a": 1}}})
    assert res.status_code == 200
    assert (await client.get(f"/simulators/{sid}/config", headers=me)).json()["data"]["selected_flow_recipe_ids"] == ["x"]
    res = await client.put(f"/simulators/{sid}", headers=me, json={"simulator_name": "S2", "save_status": "complete"})
    assert res.json()["data"]["simulator_name"] == "S2"
    assert (await client.get(f"/simulators/{sid}", headers=me)).json()["data"]["save_status"] == "complete"

    # copy needs view access; the copy belongs to the copier
    assert (await client.post(f"/simulators/{sid}/copy", headers=other, json={"simulator_name": "c"})).status_code == 403
    uid = str(other_user.user_id)
    res = await client.post(f"/simulators/{sid}/viewers", headers=me, json={"user_id": uid})
    assert uid in res.json()["data"]["viewers"]
    res = await client.post(f"/simulators/{sid}/copy", headers=other, json={"simulator_name": "copy"})
    assert res.status_code == 200, res.text
    copy = res.json()["data"]
    assert copy["owner_id"] == uid
    assert (await client.get(f"/simulators/{copy['simulator_id']}/config", headers=other)).json()["data"]["selected_flow_recipe_ids"] == ["x"]
    assert (await client.get(f"/simulators/{copy['simulator_id']}", headers=me)).status_code == 403

    res = await client.post(f"/simulators/{sid}/editors", headers=me, json={"user_id": uid})
    assert uid in res.json()["data"]["editors"]
    res = await client.delete(f"/simulators/{sid}/editors/{uid}", headers=me)
    assert uid not in res.json()["data"]["editors"] and uid in res.json()["data"]["viewers"]
    res = await client.delete(f"/simulators/{sid}/viewers/{uid}", headers=me)
    assert res.json()["data"]["viewers"] == []

    assert (await client.delete(f"/simulators/{sid}", headers=other)).status_code == 403
    assert (await client.delete(f"/simulators/{sid}", headers=me)).status_code == 200
    assert (await client.get(f"/simulators/{sid}", headers=me)).status_code == 404


@pytest.mark.asyncio
async def test_generate_and_bundle_follow_access(client, db_session, test_user, other_user, admin_user):
    me, other, admin = bearer(test_user), bearer(other_user), bearer(admin_user)
    eid, fr_id = await _build_equipment(client, me)

    sim = (await client.post("/simulators", headers=me, json={"simulator_name": "Gen"})).json()["data"]
    sid = sim["simulator_id"]
    assert (await client.post(f"/simulators/{sid}/generate", headers=me)).status_code == 404  # no equipment yet
    res = await client.put(f"/simulators/{sid}", headers=me, json={"equipment_id": eid})
    assert res.status_code == 200, res.text
    res = await client.put(f"/simulators/{sid}/config", headers=me,
                           json={"selected_flow_recipe_ids": [fr_id], "module_time_configs": {}})
    assert res.status_code == 200

    res = await client.post(f"/simulators/{sid}/generate", headers=me)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["eqp_model"].startswith("GenEq--") and "/" not in res.json()["data"]["eqp_model"]
    res = await client.post(f"/equipment/{eid}/generate", headers=me)
    assert res.status_code == 200, res.text
    assert res.json()["data"] == {"eqp_model": "GenEq"}

    # Viewers cannot generate (it is an edit-level action); admins cannot read content.
    uid = str(other_user.user_id)
    await client.post(f"/simulators/{sid}/viewers", headers=me, json={"user_id": uid})
    assert (await client.post(f"/simulators/{sid}/generate", headers=other)).status_code == 403
    assert (await client.post(f"/simulators/{sid}/bundle", headers=admin)).status_code == 403
    assert (await client.post(f"/equipment/{eid}/generate", headers=admin)).status_code == 403

    # Training servers use the internal key and get a tarball with eqp_model/ at the root.
    res = await client.post(f"/simulators/{sid}/bundle", headers=INTERNAL)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(res.content), mode="r:gz") as tar:
        names = tar.getnames()
    assert "eqp_model" in names and any(n.endswith("env_config.json") for n in names)
    res = await client.get("/simulators", headers=INTERNAL)
    assert res.status_code == 200 and any(s["simulator_id"] == sid for s in res.json()["data"])
    assert (await client.get("/simulators", headers={"X-Api-Key": "wrong"})).status_code == 401

    # A simulator whose equipment access was revoked can no longer be generated by that user.
    editor = await make_user(db_session)
    ed = bearer(editor)
    await client.post(f"/shares/simulator/{sid}", headers=me, json={"principal_type": "user", "email": editor.user_email, "permission": "edit"})
    assert (await client.post(f"/simulators/{sid}/generate", headers=ed)).status_code == 403  # no equipment access
    await client.post(f"/shares/equipment/{eid}", headers=me, json={"principal_type": "user", "email": editor.user_email})
    assert (await client.post(f"/simulators/{sid}/generate", headers=ed)).status_code == 200
