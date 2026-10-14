"""Data-migration task: recipes/modules regain their equipment link and owner."""
import pytest
from sqlalchemy import text

from app.tasks.migrate_ownership import OwnershipMigration
from tests.conftest import bearer, make_user


@pytest.mark.asyncio
async def test_migration_relinks_children_and_reports_orphans(client, db_session, test_user):
    me = bearer(test_user)
    pr = (await client.post("/process-recipes", headers=me, json={"process_recipe_name": "P"})).json()["data"]
    fr = (await client.post("/flow-recipes", headers=me, json={"flow_recipe_name": "F"})).json()["data"]
    mod = (await client.post("/modules", headers=me, json={"module_name": "M", "module_type": "robot"})).json()["data"]
    eq = (await client.post("/equipment", headers=me, json={"equipment_name": "E"})).json()["data"]
    res = await client.put(f"/equipment/{eq['equipment_id']}/config", headers=me, json={
        "equipment_name": "E", "cluster_type": "single_cluster",
        "modules": [{"module_id": mod["module_id"], "cluster": ["efem"]}], "timetables": {},
        "flow_recipe_ids": [fr["flow_recipe_id"], "junk"], "process_recipe_ids": [pr["process_recipe_id"]]})
    assert res.status_code == 200, res.text
    orphan = (await client.post("/process-recipes", headers=me, json={"process_recipe_name": "Orphan"})).json()["data"]

    # Simulate pre-migration rows: no owner, no equipment link.
    await db_session.execute(text("UPDATE process_recipes SET owner_id = NULL, equipment_id = NULL"))
    await db_session.execute(text("UPDATE flow_recipes SET owner_id = NULL, equipment_id = NULL"))
    await db_session.execute(text("UPDATE modules SET owner_id = NULL, equipment_id = NULL"))
    await db_session.commit()

    report = await OwnershipMigration().run(db_session, dry_run=True)
    assert report.dry_run and report.equipment_scanned >= 1
    assert orphan["process_recipe_id"] in report.orphan_process_recipes
    assert pr["process_recipe_id"] in report.orphan_process_recipes  # nothing changed yet

    report = await OwnershipMigration().run(db_session)
    assert report.flow_recipes_linked >= 1 and report.process_recipes_linked >= 1 and report.modules_linked >= 1
    assert report.orphan_process_recipes == [orphan["process_recipe_id"]]
    assert report.orphan_flow_recipes == [] and report.orphan_modules == []
    row = (await db_session.execute(text("SELECT owner_id::text, equipment_id::text FROM modules WHERE module_id = :id"),
                                    {"id": mod["module_id"]})).one()
    assert row == (str(test_user.user_id), eq["equipment_id"])
    assert (await client.get(f"/flow-recipes/{fr['flow_recipe_id']}", headers=me)).json()["data"]["owner_id"] == str(test_user.user_id)

    keeper = await make_user(db_session)
    report = await OwnershipMigration().run(db_session, assign_orphans_to=keeper.user_email.upper())
    assert report.orphans_assigned_to == keeper.user_email
    assert (await OwnershipMigration().run(db_session, dry_run=True)).orphan_process_recipes == []
    with pytest.raises(SystemExit):
        await OwnershipMigration().run(db_session, assign_orphans_to="nobody@example.com")

    # Unreadable config files are reported, not fatal.
    await db_session.execute(text("UPDATE equipment SET equipment_configuration_file_path = '/nonexistent/x.json' "
                                  "WHERE equipment_id = :id"), {"id": eq["equipment_id"]})
    await db_session.commit()
    report = await OwnershipMigration().run(db_session, dry_run=True)
    assert eq["equipment_id"] in report.equipment_unreadable
