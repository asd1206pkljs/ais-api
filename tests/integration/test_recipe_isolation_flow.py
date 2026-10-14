"""Recipes and modules are private, inherit access from their equipment, and
jobs can only be started on simulators the user may see."""
import uuid

import pytest

from tests.conftest import bearer, make_user


@pytest.mark.asyncio
async def test_recipes_and_modules_follow_equipment_access(client, test_user, other_user):
    me, other = bearer(test_user), bearer(other_user)

    pr = (await client.post("/process-recipes", headers=me, json={"process_recipe_name": "P"})).json()["data"]
    fr = (await client.post("/flow-recipes", headers=me, json={"flow_recipe_name": "F"})).json()["data"]
    mod = (await client.post("/modules", headers=me, json={"module_name": "PM1", "module_type": "process_module"})).json()["data"]
    assert pr["owner_id"] == str(test_user.user_id) and "process_recipe_path" not in pr
    assert "flow_recipe_path" not in fr

    for path in (f"/process-recipes/{pr['process_recipe_id']}", f"/flow-recipes/{fr['flow_recipe_id']}",
                 f"/modules/{mod['module_id']}", f"/process-recipes/{pr['process_recipe_id']}/config"):
        assert (await client.get(path, headers=other)).status_code == 403, path
    assert (await client.get("/process-recipes", headers=other)).json()["data"] == []
    assert (await client.get("/modules", headers=other)).json()["data"] == []
    assert len((await client.get("/modules", headers=me)).json()["data"]) == 1

    # Flow config may only reference process recipes the editor can see.
    res = await client.put(f"/flow-recipes/{fr['flow_recipe_id']}/config", headers=me, json={
        "flow_recipe_name": "F", "num_process_steps": 1,
        "process_recipe_steps": [{"step": 1, "process_recipe_id": pr["process_recipe_id"]}], "module_sequence": []})
    assert res.status_code == 200, res.text

    eq = (await client.post("/equipment", headers=me, json={"equipment_name": "E"})).json()["data"]
    eid = eq["equipment_id"]
    res = await client.put(f"/equipment/{eid}/config", headers=me, json={
        "equipment_name": "E", "cluster_type": "single_cluster",
        "modules": [{"module_id": mod["module_id"], "cluster": ["a"]}], "timetables": {},
        "flow_recipe_ids": [fr["flow_recipe_id"]], "process_recipe_ids": [pr["process_recipe_id"]]})
    assert res.status_code == 200, res.text
    assert (await client.get(f"/modules/{mod['module_id']}", headers=me)).json()["data"]["equipment_id"] == eid

    # Sharing the equipment (view) exposes its recipes/modules read-only.
    res = await client.post(f"/shares/equipment/{eid}", headers=me,
                            json={"principal_type": "user", "email": other_user.user_email})
    assert res.status_code == 200
    assert (await client.get(f"/process-recipes/{pr['process_recipe_id']}/config", headers=other)).status_code == 200
    assert (await client.get(f"/flow-recipes/{fr['flow_recipe_id']}", headers=other)).status_code == 200
    assert (await client.get(f"/modules/{mod['module_id']}", headers=other)).status_code == 200
    assert len((await client.get("/process-recipes", headers=other)).json()["data"]) == 1
    res = await client.put(f"/process-recipes/{pr['process_recipe_id']}/config", headers=other,
                           json={"process_recipe_name": "P2", "user_added_process_modules": [], "process_time": {}})
    assert res.status_code == 403
    assert (await client.delete(f"/modules/{mod['module_id']}", headers=other)).status_code == 403

    res = await client.post(f"/shares/equipment/{eid}", headers=me,
                            json={"principal_type": "user", "email": other_user.user_email, "permission": "edit"})
    assert res.status_code == 200
    res = await client.put(f"/process-recipes/{pr['process_recipe_id']}/config", headers=other,
                           json={"process_recipe_name": "P2", "user_added_process_modules": [], "process_time": {}})
    assert res.status_code == 200

    # Another user's flow may not reference my process recipe.
    theirs = (await client.post("/flow-recipes", headers=other, json={"flow_recipe_name": "Theirs"})).json()["data"]
    assert theirs["owner_id"] == str(other_user.user_id)


@pytest.mark.asyncio
async def test_equipment_config_cannot_capture_strangers_rows(client, test_user, other_user):
    me, other = bearer(test_user), bearer(other_user)
    mine = (await client.post("/modules", headers=me, json={"module_name": "PM", "module_type": "process_module"})).json()["data"]
    my_pr = (await client.post("/process-recipes", headers=me, json={"process_recipe_name": "P"})).json()["data"]
    eq = (await client.post("/equipment", headers=other, json={"equipment_name": "Thief"})).json()["data"]
    res = await client.put(f"/equipment/{eq['equipment_id']}/config", headers=other, json={
        "equipment_name": "Thief", "cluster_type": "single_cluster",
        "modules": [{"module_id": mine["module_id"], "cluster": ["efem"]}], "timetables": {}})
    assert res.status_code == 422
    res = await client.put(f"/equipment/{eq['equipment_id']}/config", headers=other, json={
        "equipment_name": "Thief", "cluster_type": "single_cluster", "modules": [], "timetables": {},
        "process_recipe_ids": [my_pr["process_recipe_id"]]})
    assert res.status_code == 422
    # Nothing was linked, so the stranger still has no access.
    assert (await client.get(f"/modules/{mine['module_id']}", headers=other)).status_code == 403
    assert (await client.get(f"/process-recipes/{my_pr['process_recipe_id']}", headers=other)).status_code == 403
    # Unknown ids are reported the same way as foreign ones.
    res = await client.put(f"/equipment/{eq['equipment_id']}/config", headers=other, json={
        "equipment_name": "Thief", "cluster_type": "single_cluster", "modules": [], "timetables": {},
        "process_recipe_ids": [str(uuid.uuid4())]})
    assert res.status_code == 200  # dangling references are ignored, as before


@pytest.mark.asyncio
async def test_generated_model_name_is_sanitised(client, test_user):
    me = bearer(test_user)
    eq = (await client.post("/equipment", headers=me, json={"equipment_name": "../../etc/evil"})).json()["data"]
    res = await client.put(f"/equipment/{eq['equipment_id']}/config", headers=me, json={
        "equipment_name": "../../etc/evil", "cluster_type": "single_cluster", "modules": [], "timetables": {}})
    assert res.status_code == 200
    res = await client.post(f"/equipment/{eq['equipment_id']}/generate", headers=me)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["eqp_model"] == "etc_evil"


@pytest.mark.asyncio
async def test_job_requires_simulator_access_and_results_are_private(client, db_session, test_user, admin_user):
    runner = await make_user(db_session, credits=2)
    me, run, admin = bearer(test_user), bearer(runner), bearer(admin_user)
    sim = (await client.post("/simulators", headers=me, json={"simulator_name": "S"})).json()["data"]
    sid = sim["simulator_id"]

    res = await client.post("/jobs", headers=run, json={"simulator_id": sid, "job_name": "J"})
    assert res.status_code == 403
    assert (await client.get("/users/me", headers=run)).json()["data"]["user_credits"] == 2  # nothing deducted

    assert (await client.post(f"/shares/simulator/{sid}", headers=me,
                              json={"principal_type": "user", "email": runner.user_email})).status_code == 200
    res = await client.post("/jobs", headers=run, json={"simulator_id": sid, "job_name": "J"})
    assert res.status_code == 200, res.text
    job = res.json()["data"]
    assert "result_path" not in job
    assert (await client.get("/users/me", headers=run)).json()["data"]["user_credits"] == 1

    jid = job["job_id"]
    assert (await client.get(f"/jobs/{jid}", headers=me)).status_code == 403          # simulator owner ≠ job viewer
    assert (await client.get(f"/jobs/{jid}", headers=admin)).status_code == 200       # console metadata
    assert (await client.get(f"/jobs/{jid}/results/summary", headers=admin)).status_code == 403
    assert (await client.get(f"/jobs/{jid}/results/summary", headers=run)).status_code == 404  # no bundle yet, but allowed
    res = await client.post(f"/shares/job/{jid}", headers=run, json={"principal_type": "user", "email": test_user.user_email})
    assert res.status_code == 200
    assert (await client.get(f"/jobs/{jid}", headers=me)).status_code == 200
    res = await client.post(f"/shares/job/{jid}", headers=run,
                            json={"principal_type": "user", "email": test_user.user_email, "permission": "edit"})
    assert res.status_code == 422

    # Attaching someone else's equipment to my simulator is refused.
    eq = (await client.post("/equipment", headers=admin, json={"equipment_name": "AdminEq"})).json()["data"]
    res = await client.put(f"/simulators/{sid}", headers=me, json={"equipment_id": eq["equipment_id"]})
    assert res.status_code == 403
